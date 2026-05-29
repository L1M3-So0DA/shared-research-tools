local function trim(text)
  return text:gsub("^%s+", ""):gsub("%s+$", "")
end

local function plain_equation_number(text)
  return text:match("^%([%d%.]+%)%.?$")
end

local function split_trailing_equation_number(text)
  local body, number = text:match("^(.-)\\qquad%s*{%s*(%([%d%.]+%))%s*}%s*$")
  if body then
    return trim(body), number
  end
  body, number = text:match("^(.-)\\qquad%s*(%([%d%.]+%))%s*$")
  if body then
    return trim(body), number
  end
  return nil, nil
end

function Math(el)
  if plain_equation_number(el.text) then
    return pandoc.Str(el.text)
  end

  if el.mathtype == "DisplayMath" then
    local body, number = split_trailing_equation_number(el.text)
    if body then
      return {
        pandoc.Str("$$" .. body .. "$$"),
        pandoc.Space(),
        pandoc.Str(number)
      }
    end
    return pandoc.Str("$$" .. el.text .. "$$")
  end
  return pandoc.Str("$" .. el.text .. "$")
end
