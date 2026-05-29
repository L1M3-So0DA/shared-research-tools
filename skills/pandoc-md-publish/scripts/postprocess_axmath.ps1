param(
    [Parameter(Mandatory = $true)]
    [string]$InputDocx,

    [string]$OutputDocx,

    [string]$TemplatePath,

    [string]$LogPath,

    [switch]$Visible,

    [switch]$Force
)

$ErrorActionPreference = 'Stop'

function Resolve-AbsolutePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [switch]$AllowMissing
    )

    if ($AllowMissing) {
        $resolvedDirectory = [System.IO.Path]::GetDirectoryName($Path)
        if ([string]::IsNullOrWhiteSpace($resolvedDirectory)) {
            $resolvedDirectory = (Get-Location).Path
        }
        elseif (-not [System.IO.Path]::IsPathRooted($resolvedDirectory)) {
            $resolvedDirectory = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $resolvedDirectory))
        }

        $fileName = [System.IO.Path]::GetFileName($Path)
        return [System.IO.Path]::GetFullPath((Join-Path $resolvedDirectory $fileName))
    }

    return (Resolve-Path -LiteralPath $Path).Path
}

function New-DefaultOutputPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InputPath
    )

    $directory = [System.IO.Path]::GetDirectoryName($InputPath)
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($InputPath)
    return Join-Path $directory ($stem + '.axmath.docx')
}

function Resolve-AxMathTemplatePath {
    param(
        [string]$UserSuppliedPath
    )

    $candidates = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($UserSuppliedPath)) {
        $candidates.Add((Resolve-AbsolutePath -Path $UserSuppliedPath -AllowMissing))
        if ([System.IO.Path]::GetExtension($UserSuppliedPath) -ieq '.exe') {
            $exeDirectory = Split-Path -Parent (Resolve-AbsolutePath -Path $UserSuppliedPath -AllowMissing)
            $candidates.Add((Join-Path $exeDirectory 'MSOffice\AxMath.dotm'))
        }
    }

    $candidates.Add('C:\Software\AxMath\MSOffice\AxMath.dotm')
    $candidates.Add('C:\Program Files (x86)\AxMath\MSOffice\AxMath.dotm')
    $candidates.Add('C:\Program Files\AxMath\MSOffice\AxMath.dotm')

    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return $candidate
        }
    }

    $searched = $candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
    throw 'AxMath template not found. Checked: ' + ($searched -join '; ')
}

function Write-Log {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $script:ResolvedLogPath -Value ('[{0}] {1}' -f $timestamp, $Message) -Encoding UTF8
}

function Release-ComObjectIfNeeded {
    param(
        $ComObject
    )

    if ($null -ne $ComObject -and [System.Runtime.InteropServices.Marshal]::IsComObject($ComObject)) {
        [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($ComObject)
    }
}

function Get-LatexEquationTargets {
    param(
        [Parameter(Mandatory = $true)]
        $Document,

        [switch]$Quiet
    )

    $pattern = '(?s)(?<!\\)\$\$(.+?)(?<!\\)\$\$|(?<!\\)\$(.+?)(?<!\\)\$'
    $matches = [regex]::Matches($Document.Content.Text, $pattern)
    $targets = New-Object System.Collections.Generic.List[object]

    for ($index = 0; $index -lt $matches.Count; $index++) {
        $match = $matches[$index]
        $kind = if ($match.Value.StartsWith('$$')) { 'display' } else { 'inline' }
        $preview = $match.Value.Replace([string][char]13, ' ').Replace([string][char]7, ' ').Trim()
        if ($preview.Length -gt 80) {
            $preview = $preview.Substring(0, 80) + '...'
        }

        $targets.Add([pscustomobject]@{
            Index = $index + 1
            Kind = $kind
            Start = $match.Index
            End = $match.Index + $match.Length
            Preview = $preview
        })
    }

    if (-not $Quiet) {
        $inlineCount = ($targets | Where-Object { $_.Kind -eq 'inline' }).Count
        $displayCount = ($targets | Where-Object { $_.Kind -eq 'display' }).Count
        Write-Log ('Detected ' + $targets.Count + ' delimited LaTeX equations. Inline=' + $inlineCount + ', Display=' + $displayCount)
    }
    return $targets
}

function Test-WordHeadingStyle {
    param(
        [string]$StyleName
    )

    return (
        $StyleName -match '^Heading\s*[0-9]+$' -or
        $StyleName -match '^标题\s*[0-9]+$' -or
        $StyleName -eq 'Title' -or
        $StyleName -eq '标题'
    )
}

function Test-WordHeadingParagraph {
    param(
        [Parameter(Mandatory = $true)]
        $ParagraphRange
    )

    try {
        $outlineLevel = [int]$ParagraphRange.ParagraphFormat.OutlineLevel
        if (($outlineLevel -ge 1) -and ($outlineLevel -le 9)) {
            return $true
        }
    }
    catch {
        # Fall back to localized style-name matching below.
    }

    return Test-WordHeadingStyle -StyleName ([string]$ParagraphRange.Style.NameLocal)
}

function Get-AxMathBodyConversionRanges {
    param(
        [Parameter(Mandatory = $true)]
        $Document
    )

    $groups = New-Object System.Collections.Generic.List[object]
    $currentGroup = $null

    for ($index = 1; $index -le $Document.Paragraphs.Count; $index++) {
        $paragraphRange = $null
        try {
            $paragraphRange = $Document.Paragraphs.Item($index).Range
            $text = [string]$paragraphRange.Text
            $hasFormula = $text -match '\$'

            if (Test-WordHeadingParagraph -ParagraphRange $paragraphRange) {
                if (($null -ne $currentGroup) -and $currentGroup.HasFormula) {
                    $groups.Add($currentGroup)
                }
                $currentGroup = $null
                continue
            }

            if ($null -eq $currentGroup) {
                $currentGroup = [pscustomobject]@{
                    StartParagraph = $index
                    EndParagraph = $index
                    Start = [int]$paragraphRange.Start
                    End = [int]$paragraphRange.End
                    HasFormula = [bool]$hasFormula
                    FormulaParagraphs = New-Object System.Collections.Generic.List[int]
                }
            }
            else {
                $currentGroup.EndParagraph = $index
                $currentGroup.End = [int]$paragraphRange.End
                if ($hasFormula) {
                    $currentGroup.HasFormula = $true
                }
            }

            if ($hasFormula) {
                $currentGroup.FormulaParagraphs.Add($index)
            }
        }
        finally {
            Release-ComObjectIfNeeded -ComObject $paragraphRange
        }
    }

    if (($null -ne $currentGroup) -and $currentGroup.HasFormula) {
        $groups.Add($currentGroup)
    }

    return $groups
}

function Invoke-AxMathBodyRangeConversion {
    param(
        [Parameter(Mandatory = $true)]
        $WordApplication,

        [Parameter(Mandatory = $true)]
        $Document
    )

    $groups = @(Get-AxMathBodyConversionRanges -Document $Document)
    if ($groups.Count -eq 0) {
        throw 'No body paragraph ranges containing delimited LaTeX equations were found for AxMath conversion.'
    }

    Write-Log ('Segmented body conversion ranges: {0}.' -f $groups.Count)
    $callback = $null
    foreach ($group in ($groups | Sort-Object Start -Descending)) {
        $formulaParagraphs = $group.FormulaParagraphs -join ','
        Write-Log (
            'Converting body range P{0}-P{1}; formula paragraphs=[{2}]; range={3}-{4}.' -f
            $group.StartParagraph,
            $group.EndParagraph,
            $formulaParagraphs,
            $group.Start,
            $group.End
        )
        $range = $null
        try {
            $range = $Document.Range([int]$group.Start, [int]$group.End)
            $range.Select()
            $WordApplication.Run('AMSTeX2AM', ([ref]$callback))
        }
        finally {
            Release-ComObjectIfNeeded -ComObject $range
        }
    }
    Write-Log 'Segmented body AMSTeX2AM conversion finished.'
}

function Get-AxMathEquationCount {
    param(
        [Parameter(Mandatory = $true)]
        $Document
    )

    $count = 0
    foreach ($inlineShape in $Document.InlineShapes) {
        try {
            if (($inlineShape.Type -eq 1) -and ($inlineShape.OLEFormat.ProgID -eq 'Equation.AxMath')) {
                $count += 1
            }
        }
        catch {
            continue
        }
    }
    return $count
}

function Assert-AxMathConversionComplete {
    param(
        [Parameter(Mandatory = $true)]
        $Document,

        [Parameter(Mandatory = $true)]
        [int]$ExpectedCount
    )

    $residual = (Get-LatexEquationTargets -Document $Document -Quiet).Count
    $actual = Get-AxMathEquationCount -Document $Document
    Write-Log ('Verification: expected={0}, axmath={1}, residual_tex={2}' -f $ExpectedCount, $actual, $residual)

    if (($residual -ne 0) -or ($actual -ne $ExpectedCount)) {
        throw ('AxMath verification failed: expected {0} equations, found {1} AxMath objects and {2} residual TeX formulas.' -f $ExpectedCount, $actual, $residual)
    }
}

$resolvedInputDocx = Resolve-AbsolutePath -Path $InputDocx
$resolvedTemplatePath = Resolve-AxMathTemplatePath -UserSuppliedPath $TemplatePath
$resolvedOutputDocx = if ($OutputDocx) {
    Resolve-AbsolutePath -Path $OutputDocx -AllowMissing
}
else {
    New-DefaultOutputPath -InputPath $resolvedInputDocx
}

$script:ResolvedLogPath = if ($LogPath) {
    Resolve-AbsolutePath -Path $LogPath -AllowMissing
}
else {
    $resolvedOutputDocx + '.axmath.log'
}

if (-not (Test-Path -LiteralPath $resolvedInputDocx -PathType Leaf)) {
    throw 'Input docx not found: ' + $resolvedInputDocx
}
if ((Test-Path -LiteralPath $resolvedOutputDocx -PathType Leaf) -and -not $Force) {
    throw 'Output docx already exists. Use -Force to overwrite: ' + $resolvedOutputDocx
}

$outputDirectory = Split-Path -Parent $resolvedOutputDocx
if (-not [string]::IsNullOrWhiteSpace($outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
}
$logDirectory = Split-Path -Parent $script:ResolvedLogPath
if (-not [string]::IsNullOrWhiteSpace($logDirectory)) {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
}

Remove-Item -LiteralPath $script:ResolvedLogPath -ErrorAction SilentlyContinue
Write-Log 'AxMath post-processing started.'
Write-Log ('Input docx: ' + $resolvedInputDocx)
Write-Log ('Output docx: ' + $resolvedOutputDocx)
Write-Log ('AxMath template: ' + $resolvedTemplatePath)

$word = $null
$document = $null

try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = [bool]$Visible
    $word.DisplayAlerts = 0
    Write-Log 'Word COM started.'

    $word.Templates.LoadBuildingBlocks()
    $existingAxMathAddIns = @($word.AddIns | Where-Object { $_.Name -eq 'AxMath.dotm' })
    if ($existingAxMathAddIns.Count -gt 0) {
        Write-Log ('AxMath add-in already available. Count={0}.' -f $existingAxMathAddIns.Count)
    }
    else {
        $word.AddIns.Add($resolvedTemplatePath, $true) | Out-Null
        Write-Log ('AxMath add-in added from template path: ' + $resolvedTemplatePath)
    }
    foreach ($addIn in $word.AddIns) {
        if (($addIn.Name -eq 'AxMath.dotm') -and (-not $addIn.Installed)) {
            $addIn.Installed = $true
        }
    }
    Write-Log 'AxMath add-in loaded.'

    $document = $word.Documents.Open($resolvedInputDocx)
    $document.Activate()
    Write-Log 'Input document opened.'

    $targets = Get-LatexEquationTargets -Document $document
    if ($targets.Count -eq 0) {
        throw 'No delimited LaTeX equations were found for AxMath conversion.'
    }

    Invoke-AxMathBodyRangeConversion -WordApplication $word -Document $document
    Assert-AxMathConversionComplete -Document $document -ExpectedCount $targets.Count

    $wdFormatXMLDocument = 12
    if ((Test-Path -LiteralPath $resolvedOutputDocx -PathType Leaf) -and $Force) {
        Remove-Item -LiteralPath $resolvedOutputDocx -Force
    }
    $document.SaveAs([ref]$resolvedOutputDocx, [ref]$wdFormatXMLDocument)
    Write-Log 'Output document saved.'

    $outputFile = Get-Item -LiteralPath $resolvedOutputDocx
    Write-Output ('OutputDocx: ' + $outputFile.FullName)
    Write-Output ('SizeBytes: ' + $outputFile.Length)
    Write-Output ('LastWriteTime: ' + $outputFile.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))
    Write-Output ('LogPath: ' + $script:ResolvedLogPath)
}
catch {
    Write-Log ('ERROR: ' + $_.Exception.Message)
    throw
}
finally {
    if ($document -ne $null) {
        try {
            $document.Close()
            Release-ComObjectIfNeeded -ComObject $document
            Write-Log 'Document closed.'
        }
        catch {
            Write-Log ('Document close failed: ' + $_.Exception.Message)
        }
    }
    if ($word -ne $null) {
        try {
            $word.Quit()
            Release-ComObjectIfNeeded -ComObject $word
            Write-Log 'Word quit.'
        }
        catch {
            Write-Log ('Word quit failed: ' + $_.Exception.Message)
        }
    }

    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}
