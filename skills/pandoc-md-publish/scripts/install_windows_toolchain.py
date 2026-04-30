from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from convert_document import inspect_toolchain, resolve_executable


DEFAULT_INSTALL_DIR = Path(r"C:\Program Files\Pandoc")
PANDOC_GITHUB_API = "https://api.github.com/repos/jgm/pandoc"
CROSSREF_GITHUB_API = "https://api.github.com/repos/lierdakil/pandoc-crossref"
PANDOC_WINGET_ID = "JohnMacFarlane.Pandoc"
SEVEN_ZIP_WINGET_ID = "7zip.7zip"
PANDOC_CHOCO_ID = "pandoc"
SEVEN_ZIP_CHOCO_ID = "7zip"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "pandoc-md-publish-windows-installer",
    "X-GitHub-Api-Version": "2022-11-28",
}
VERSION_PATTERN = re.compile(r"\b(\d+(?:\.\d+)+)\b")
CROSSREF_BUILD_PATTERN = re.compile(r"built with Pandoc v(\d+)", re.IGNORECASE)
COMMON_ARCHIVE_TOOL_PATHS = [
    Path(r"C:\Program Files\7-Zip\7z.exe"),
    Path(r"C:\Program Files\7-Zip\7za.exe"),
    Path(r"C:\Program Files\7-Zip\7zz.exe"),
    Path(r"C:\Program Files\Bandizip\Bandizip.exe"),
    Path(r"C:\Program Files\Bandizip\bz.exe"),
    Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
    Path(r"C:\Program Files (x86)\7-Zip\7za.exe"),
    Path(r"C:\Program Files (x86)\7-Zip\7zz.exe"),
    Path(r"C:\Program Files (x86)\Bandizip\Bandizip.exe"),
    Path(r"C:\Program Files (x86)\Bandizip\bz.exe"),
]

TOOLCHAIN_HINT_FILE = Path.home() / ".pandoc-md-publish" / "windows-toolchain.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap Pandoc and pandoc-crossref on Windows.")
    parser.add_argument(
        "--install-dir",
        help=(
            "Target directory for Pandoc and pandoc-crossref. "
            "Defaults to the current Pandoc directory or C:\\Program Files\\Pandoc."
        ),
    )
    parser.add_argument(
        "--pandoc-version",
        help="Optional Pandoc version or tag to install. Defaults to the latest release.",
    )
    parser.add_argument(
        "--skip-package-manager",
        action="store_true",
        help="Skip winget/choco and download Pandoc release archives instead.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reinstall Pandoc and pandoc-crossref even if matching executables already exist in the target directory.",
    )
    return parser


def normalize_version_tag(version: str) -> str:
    return version.strip().removeprefix("v")


def parse_first_version_string(text: str) -> str:
    match = VERSION_PATTERN.search(text)
    if not match:
        raise ValueError("No semantic version string could be parsed from the command output.")
    return match.group(1)


def parse_major_from_version_string(version: str) -> int:
    return int(version.split(".", 1)[0])


def parse_crossref_build_major(version_output: str) -> int:
    match = CROSSREF_BUILD_PATTERN.search(version_output)
    if not match:
        raise ValueError("The pandoc-crossref build target could not be parsed from its version output.")
    return int(match.group(1))


def github_api_json(url: str) -> dict | list:
    request = urllib.request.Request(url, headers=GITHUB_HEADERS)
    first_error: Exception | None = None
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            first_error = exc
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        first_error = exc

    headers_literal = build_powershell_hashtable(GITHUB_HEADERS)
    script = (
        "$ProgressPreference='SilentlyContinue'; "
        f"$headers = {headers_literal}; "
        f"Invoke-RestMethod -Headers $headers -Uri '{escape_powershell_single_quoted(url)}' -TimeoutSec 60 | "
        "ConvertTo-Json -Depth 20 -Compress"
    )

    try:
        payload = run_powershell_command(script, f"PowerShell GitHub API request for {url}")
        return json.loads(payload)
    except Exception as fallback_exc:
        raise RuntimeError(f"Failed to download {url}: {first_error}\nPowerShell fallback also failed: {fallback_exc}") from fallback_exc


def download_file(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers=GITHUB_HEADERS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as destination_file:
            shutil.copyfileobj(response, destination_file)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        headers_literal = build_powershell_hashtable(GITHUB_HEADERS)
        script = (
            "$ProgressPreference='SilentlyContinue'; "
            f"$headers = {headers_literal}; "
            f"Invoke-WebRequest -Headers $headers -Uri '{escape_powershell_single_quoted(url)}' "
            f"-OutFile '{escape_powershell_single_quoted(str(destination))}' -TimeoutSec 120"
        )

        try:
            run_powershell_command(script, f"PowerShell download for {url}")
        except Exception as fallback_exc:
            raise RuntimeError(f"Failed to download {url}: {exc}\nPowerShell fallback also failed: {fallback_exc}") from fallback_exc


def escape_powershell_single_quoted(value: str) -> str:
    return value.replace("'", "''")


def build_powershell_hashtable(items: dict[str, str]) -> str:
    parts = [
        f"'{escape_powershell_single_quoted(key)}' = '{escape_powershell_single_quoted(value)}'"
        for key, value in items.items()
    ]
    return "@{ " + "; ".join(parts) + " }"


def run_powershell_command(script: str, description: str) -> str:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        output = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"{description} failed: {output}")
    return (completed.stdout or completed.stderr).strip()


def get_command_output(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        output = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{output}")
    return (completed.stdout or completed.stderr).strip()


def run_checked_command(command: list[str], description: str) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        output = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"{description} failed: {output}")


def resolve_archive_extractor() -> str | None:
    for command_name in ("7z.exe", "7za.exe", "7zz.exe", "Bandizip.exe", "bz.exe"):
        resolved = resolve_executable(command_name, COMMON_ARCHIVE_TOOL_PATHS)
        if resolved:
            return resolved
    return None


def build_winget_install_command(package_id: str, version: str | None = None) -> list[str]:
    command = [
        "winget",
        "install",
        "--id",
        package_id,
        "-e",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]
    if version:
        command.extend(["--version", normalize_version_tag(version)])
    return command


def build_choco_install_command(package_id: str, version: str | None = None) -> list[str]:
    command = ["choco", "install", package_id, "-y", "--no-progress"]
    if version:
        command.extend(["--version", normalize_version_tag(version)])
    return command


def build_package_manager_install_command(manager: str, package_id: str, version: str | None = None) -> list[str]:
    if manager == "winget":
        return build_winget_install_command(package_id, version)
    if manager == "choco":
        return build_choco_install_command(package_id, version)
    raise ValueError(f"Unsupported package manager: {manager}")


def get_local_appdata_install_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "Pandoc"
    return Path.home() / "AppData" / "Local" / "Pandoc"


def normalize_path_entry(path_entry: str) -> str:
    return path_entry.strip().strip('"').rstrip("\\/").casefold()


def prepend_path_entry(current_value: str | None, new_entry: str) -> tuple[str, bool]:
    normalized_new_entry = normalize_path_entry(new_entry)
    entries = [entry for entry in (current_value.split(";") if current_value else []) if entry]

    for entry in entries:
        if normalize_path_entry(entry) == normalized_new_entry:
            return current_value or "", False

    if entries:
        return ";".join([new_entry, *entries]), True

    return new_entry, True


def probe_install_directory(install_dir: Path) -> tuple[bool, str | None]:
    probe_path: Path | None = None

    try:
        install_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=install_dir, prefix=".pandoc-md-publish-")
        os.close(fd)
        probe_path = Path(temp_name)
        probe_path.unlink()
        return True, None
    except OSError as exc:
        if probe_path and probe_path.exists():
            try:
                probe_path.unlink()
            except OSError:
                pass
        return False, str(exc)


def prompt_for_install_directory(current_install_dir: Path, reason: str) -> Path | None:
    local_appdata_install_dir = get_local_appdata_install_dir()

    print(
        f"Default install directory '{current_install_dir}' is not usable: {reason}",
        file=sys.stderr,
    )

    if not sys.stdin.isatty():
        print(
            f"Use '{local_appdata_install_dir}' or a custom directory, then rerun the installer.",
            file=sys.stderr,
        )
        return None

    while True:
        print("Choose an alternate install directory:")
        print(f"  1) {local_appdata_install_dir}")
        print("  2) Custom directory")
        print("  3) Cancel")

        choice = input("Enter 1, 2, or 3: ").strip()

        if choice == "1":
            usable, error = probe_install_directory(local_appdata_install_dir)
            if usable:
                return local_appdata_install_dir
            print(f"Unable to use '{local_appdata_install_dir}': {error}", file=sys.stderr)
            continue

        if choice == "2":
            custom_value = input("Enter custom install directory: ").strip().strip('"')
            if not custom_value:
                print("Custom install directory cannot be empty.", file=sys.stderr)
                continue

            custom_install_dir = Path(os.path.expandvars(custom_value)).expanduser().resolve()
            usable, error = probe_install_directory(custom_install_dir)
            if usable:
                return custom_install_dir
            print(f"Unable to use '{custom_install_dir}': {error}", file=sys.stderr)
            continue

        if choice == "3":
            return None

        print("Please enter 1, 2, or 3.", file=sys.stderr)


def read_user_path_value() -> tuple[str, int | None]:
    if winreg is None:
        return "", None

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ) as key:
            value, value_type = winreg.QueryValueEx(key, "Path")
            return str(value), value_type
    except OSError:
        return "", winreg.REG_EXPAND_SZ


def write_user_path_value(path_value: str, value_type: int | None) -> None:
    if winreg is None:
        return

    registry_type = value_type if value_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) else winreg.REG_EXPAND_SZ
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, registry_type, path_value)


def write_toolchain_hint(toolchain_root: Path, pandoc_path: Path, crossref_path: Path) -> Path:
    TOOLCHAIN_HINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "install_dir": str(toolchain_root),
        "pandoc_path": str(pandoc_path),
        "pandoc_crossref_path": str(crossref_path),
    }
    TOOLCHAIN_HINT_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return TOOLCHAIN_HINT_FILE


def register_installation_discoverability(toolchain_root: Path, pandoc_path: Path, crossref_path: Path) -> dict:
    status = {
        "path_updated": False,
        "hint_written": False,
        "toolchain_root": str(toolchain_root),
        "hint_path": str(TOOLCHAIN_HINT_FILE),
        "warnings": [],
    }

    current_user_path, registry_type = read_user_path_value()
    updated_user_path, path_changed = prepend_path_entry(current_user_path, str(toolchain_root))
    if path_changed:
        try:
            write_user_path_value(updated_user_path, registry_type)
        except OSError as exc:
            status["warnings"].append(f"Unable to update the user PATH: {exc}")
        else:
            status["path_updated"] = True

    updated_process_path, _ = prepend_path_entry(os.environ.get("PATH", ""), str(toolchain_root))
    os.environ["PATH"] = updated_process_path

    try:
        write_toolchain_hint(toolchain_root, pandoc_path, crossref_path)
    except OSError as exc:
        status["warnings"].append(f"Unable to write toolchain hint: {exc}")
    else:
        status["hint_written"] = True

    return status


def detect_windows_architecture() -> str:
    machine = platform.machine().lower()
    if "arm64" in machine or "aarch64" in machine:
        return "arm64"
    return "x86_64"


def select_release_asset(assets: list[dict], name_keywords: tuple[str, ...], preferred_suffixes: tuple[str, ...]) -> dict:
    keywords = tuple(keyword.lower() for keyword in name_keywords)
    suffixes = tuple(suffix.lower() for suffix in preferred_suffixes)

    candidates: list[dict] = []
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        if keywords and not all(keyword in name for keyword in keywords):
            continue
        if suffixes and not any(name.endswith(suffix) for suffix in suffixes):
            continue
        candidates.append(asset)

    if not candidates:
        names = ", ".join(str(asset.get("name", "<unnamed>")) for asset in assets)
        raise RuntimeError(
            f"No release asset matched keywords {name_keywords!r} and suffixes {preferred_suffixes!r}. Available assets: {names}"
        )

    def asset_rank(asset: dict) -> tuple[int, str]:
        name = str(asset.get("name", "")).lower()
        for index, suffix in enumerate(suffixes):
            if name.endswith(suffix):
                return index, name
        return len(suffixes), name

    candidates.sort(key=asset_rank)
    return candidates[0]


def select_pandoc_release(version: str | None, architecture: str) -> tuple[dict, dict]:
    if version:
        release_url = f"{PANDOC_GITHUB_API}/releases/tags/{normalize_version_tag(version)}"
    else:
        release_url = f"{PANDOC_GITHUB_API}/releases/latest"

    release = github_api_json(release_url)
    assert isinstance(release, dict)
    asset = select_release_asset(
        list(release.get("assets", [])),
        ("windows", architecture),
        (".zip",),
    )
    return release, asset


def select_crossref_release(pandoc_major: int, releases: list[dict]) -> tuple[dict, dict]:
    for release in releases:
        body = str(release.get("body", ""))
        if not body:
            continue
        try:
            build_major = parse_crossref_build_major(body)
        except ValueError:
            continue
        if build_major != pandoc_major:
            continue

        asset = select_release_asset(
            list(release.get("assets", [])),
            ("windows", "x64"),
            (".zip", ".7z"),
        )
        return release, asset

    raise RuntimeError(f"No pandoc-crossref release matching Pandoc major version {pandoc_major} was found.")


def github_releases(url: str, max_pages: int = 5) -> list[dict]:
    releases: list[dict] = []
    for page in range(1, max_pages + 1):
        page_url = f"{url}?per_page=100&page={page}"
        page_releases = github_api_json(page_url)
        if not isinstance(page_releases, list) or not page_releases:
            break
        releases.extend(page_releases)
    return releases


def determine_payload_root(extract_root: Path, expected_executable: str) -> Path:
    if (extract_root / expected_executable).exists():
        return extract_root

    matches = sorted(
        extract_root.rglob(expected_executable),
        key=lambda path: len(path.relative_to(extract_root).parts),
    )
    if not matches:
        raise RuntimeError(f"{expected_executable} was not found after extracting the archive.")

    first_match = matches[0]
    top_level_name = first_match.relative_to(extract_root).parts[0]
    return extract_root / top_level_name


def copy_tree_overwrite(source_root: Path, destination_root: Path) -> None:
    destination_root.mkdir(parents=True, exist_ok=True)

    for item in source_root.iterdir():
        target = destination_root / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def flatten_single_nested_directory(root_dir: Path, expected_executable: str) -> None:
    while not (root_dir / expected_executable).exists():
        matches = sorted(
            root_dir.rglob(expected_executable),
            key=lambda path: len(path.relative_to(root_dir).parts),
        )
        if not matches:
            raise RuntimeError(f"{expected_executable} was not found in {root_dir} after extraction.")

        nested_directory = matches[0].parent
        if nested_directory == root_dir:
            return

        for item in list(nested_directory.iterdir()):
            target = root_dir / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(item), str(target))

        current = nested_directory
        while current != root_dir:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


def install_downloaded_archive(asset: dict, install_dir: Path, expected_executable: str, extractor_path: str | None = None) -> Path:
    archive_name = str(asset.get("name", "downloaded-archive"))
    download_url = str(asset["browser_download_url"])

    with tempfile.TemporaryDirectory(prefix="pandoc-md-publish-install-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        archive_path = temp_dir / archive_name
        extract_root = temp_dir / "extract"
        extract_root.mkdir(parents=True, exist_ok=True)

        print(f"Downloading {archive_name}...")
        download_file(download_url, archive_path)

        print(f"Extracting {archive_name} into {install_dir}...")
        extract_archive(archive_path, extract_root, extractor_path)

        source_root = determine_payload_root(extract_root, expected_executable)
        copy_tree_overwrite(source_root, install_dir)
        flatten_single_nested_directory(install_dir, expected_executable)

    installed = install_dir / expected_executable
    if installed.exists():
        return installed

    fallback = next(install_dir.rglob(expected_executable), None)
    if fallback:
        return fallback

    raise RuntimeError(f"{expected_executable} was not installed into {install_dir}.")


def extract_archive(archive_path: Path, destination: Path, extractor_path: str | None) -> None:
    suffix = archive_path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(destination)
        return

    if suffix == ".7z":
        py7zr = load_py7zr_module()
        if py7zr is not None:
            with py7zr.SevenZipFile(archive_path, mode="r") as archive:
                archive.extractall(path=destination)
            return

    if not extractor_path:
        raise RuntimeError(f"No archive extractor is available for {archive_path.name}.")

    extractor_name = Path(extractor_path).name.lower()
    if extractor_name in {"bandizip.exe", "bz.exe"}:
        command = [extractor_path, "x", f"-o:{destination}", "-y", str(archive_path)]
    else:
        command = [extractor_path, "x", "-y", f"-o{destination}", str(archive_path)]

    run_checked_command(command, f"Extracting {archive_path.name}")


def install_7zip_if_needed() -> str:
    extractor = resolve_archive_extractor()
    if extractor:
        return extractor

    for manager_name, package_id in (("winget", SEVEN_ZIP_WINGET_ID), ("choco", SEVEN_ZIP_CHOCO_ID)):
        if not resolve_executable(manager_name):
            continue

        command = build_package_manager_install_command(manager_name, package_id)
        print(f"Installing 7-Zip via {manager_name}...")
        run_checked_command(command, f"7-Zip installation via {manager_name}")

        extractor = resolve_archive_extractor()
        if extractor:
            return extractor

    raise RuntimeError("No compatible archive extractor was found and 7-Zip could not be installed.")


def install_pandoc_with_package_manager(install_dir: Path, version: str | None) -> Path:
    for manager_name, package_id in (("winget", PANDOC_WINGET_ID), ("choco", PANDOC_CHOCO_ID)):
        if not resolve_executable(manager_name):
            continue

        command = build_package_manager_install_command(manager_name, package_id, version)
        print(f"Installing Pandoc via {manager_name}...")
        run_checked_command(command, f"Pandoc installation via {manager_name}")

        installed = install_dir / "pandoc.exe"
        if installed.exists():
            return installed

        resolved = resolve_executable("pandoc", [install_dir / "pandoc.exe"])
        if resolved:
            return Path(resolved)

    raise RuntimeError("Pandoc package-manager installation was requested, but winget/choco did not produce a usable pandoc.exe.")


def install_pandoc_from_release(install_dir: Path, version: str | None) -> Path:
    architecture = detect_windows_architecture()
    release, asset = select_pandoc_release(version, architecture)
    print(f"Installing Pandoc from GitHub release {release.get('tag_name', '<unknown>')}...")
    return install_downloaded_archive(asset, install_dir, "pandoc.exe")


def install_crossref_from_release(install_dir: Path, pandoc_major: int) -> Path:
    releases = github_releases(f"{CROSSREF_GITHUB_API}/releases")
    release, asset = select_crossref_release(pandoc_major, releases)
    extractor = resolve_archive_extractor()
    if not extractor and str(asset.get("name", "")).lower().endswith(".7z") and not can_extract_7z_with_py7zr():
        extractor = install_7zip_if_needed()

    print(f"Installing pandoc-crossref from GitHub release {release.get('tag_name', '<unknown>')}...")
    return install_downloaded_archive(asset, install_dir, "pandoc-crossref.exe", extractor)


def load_py7zr_module():
    try:
        return importlib.import_module("py7zr")
    except ModuleNotFoundError:
        return None


def can_extract_7z_with_py7zr() -> bool:
    return load_py7zr_module() is not None


def choose_install_root(explicit_install_dir: Path | None, pandoc_path: str | None, crossref_path: str | None) -> Path:
    if explicit_install_dir is not None:
        return explicit_install_dir

    if pandoc_path:
        return Path(pandoc_path).resolve().parent

    if crossref_path:
        return Path(crossref_path).resolve().parent

    return DEFAULT_INSTALL_DIR


def version_matches(installed_version: str, requested_version: str | None) -> bool:
    if not requested_version:
        return True
    return normalize_version_tag(installed_version) == normalize_version_tag(requested_version)


def pandoc_version_matches(pandoc_path: Path, requested_version: str | None) -> bool:
    if not requested_version:
        return True

    try:
        installed_version = parse_first_version_string(get_command_output([str(pandoc_path), "--version"]))
    except Exception:
        return False

    return normalize_version_tag(installed_version) == normalize_version_tag(requested_version)


def crossref_matches_pandoc_major(crossref_path: Path, pandoc_major: int) -> bool:
    try:
        crossref_version_output = get_command_output([str(crossref_path), "--version"])
        return parse_crossref_build_major(crossref_version_output) == pandoc_major
    except Exception:
        return False


def main() -> int:
    if os.name != "nt":
        print("This installer only supports Windows.", file=sys.stderr)
        return 2

    args = build_parser().parse_args()
    explicit_install_dir = None
    if args.install_dir:
        explicit_install_dir = Path(os.path.expandvars(args.install_dir)).expanduser().resolve()

    global_pandoc = resolve_executable("pandoc", [DEFAULT_INSTALL_DIR / "pandoc.exe"])
    global_crossref = resolve_executable("pandoc-crossref", [DEFAULT_INSTALL_DIR / "pandoc-crossref.exe"])
    install_dir = choose_install_root(explicit_install_dir, global_pandoc, global_crossref)

    if install_dir == DEFAULT_INSTALL_DIR:
        usable, reason = probe_install_directory(install_dir)
        if not usable:
            fallback_install_dir = prompt_for_install_directory(install_dir, reason or "not writable")
            if fallback_install_dir is None:
                print("Installation cancelled because the default install directory is not usable.", file=sys.stderr)
                return 2
            install_dir = fallback_install_dir

    if not args.force and explicit_install_dir is None and global_pandoc and global_crossref:
        compatibility = inspect_toolchain(global_pandoc, global_crossref)
        if compatibility["compatible"]:
            registration = register_installation_discoverability(
                install_dir,
                Path(global_pandoc),
                Path(global_crossref),
            )
            if registration["path_updated"]:
                print(f"Added {registration['toolchain_root']} to the user PATH.")
            for warning in registration["warnings"]:
                print(warning, file=sys.stderr)
            print("Pandoc and pandoc-crossref are already installed and compatible.")
            print(f"Pandoc: {global_pandoc}")
            print(f"pandoc-crossref: {global_crossref}")
            return 0

    install_dir.mkdir(parents=True, exist_ok=True)

    pandoc_path = install_dir / "pandoc.exe"
    crossref_path = install_dir / "pandoc-crossref.exe"

    if not args.force and pandoc_path.exists() and crossref_path.exists():
        compatibility = inspect_toolchain(str(pandoc_path), str(crossref_path))
        if compatibility["compatible"]:
            registration = register_installation_discoverability(install_dir, pandoc_path, crossref_path)
            if registration["path_updated"]:
                print(f"Added {registration['toolchain_root']} to the user PATH.")
            for warning in registration["warnings"]:
                print(warning, file=sys.stderr)
            print("Pandoc and pandoc-crossref are already installed in the target directory.")
            print(f"Pandoc: {pandoc_path}")
            print(f"pandoc-crossref: {crossref_path}")
            return 0

    if not pandoc_path.exists() or args.force or not pandoc_version_matches(pandoc_path, args.pandoc_version):
        if install_dir == DEFAULT_INSTALL_DIR and not args.skip_package_manager:
            pandoc_path = install_pandoc_with_package_manager(install_dir, args.pandoc_version)
        else:
            pandoc_path = install_pandoc_from_release(install_dir, args.pandoc_version)

    pandoc_version_output = get_command_output([str(pandoc_path), "--version"])
    pandoc_version = parse_first_version_string(pandoc_version_output)
    pandoc_major = parse_major_from_version_string(pandoc_version)

    if not crossref_path.exists() or args.force:
        crossref_path = install_crossref_from_release(install_dir, pandoc_major)
    else:
        if not crossref_matches_pandoc_major(crossref_path, pandoc_major):
            crossref_path = install_crossref_from_release(install_dir, pandoc_major)

    final_toolchain = inspect_toolchain(str(pandoc_path), str(crossref_path))
    if not final_toolchain["compatible"]:
        warning = final_toolchain.get("warning") or "Pandoc and pandoc-crossref are incompatible after installation."
        print(warning, file=sys.stderr)
        return 2

    registration = register_installation_discoverability(install_dir, pandoc_path, crossref_path)
    if registration["path_updated"]:
        print(f"Added {registration['toolchain_root']} to the user PATH.")
    for warning in registration["warnings"]:
        print(warning, file=sys.stderr)

    print("Windows toolchain installation completed.")
    print(f"Pandoc: {pandoc_path}")
    print(f"pandoc-crossref: {crossref_path}")
    print(f"Install directory: {install_dir}")
    print(f"Pandoc version: {final_toolchain['pandoc_version']}")
    print(f"pandoc-crossref build target: {final_toolchain['pandoc_crossref_build_target']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())