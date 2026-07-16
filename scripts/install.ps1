$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$PluginId = "claude-otel-plugin@claude-otel-plugin"
$MarketplaceName = "claude-otel-plugin"
$MarketplaceSource = if ($env:MARKETPLACE_SOURCE) { $env:MARKETPLACE_SOURCE } else { (Get-Location).Path }
$MarketplaceSourceWasSet = [bool]$env:MARKETPLACE_SOURCE
$Scope = if ($env:CLAUDE_OTEL_SCOPE) { $env:CLAUDE_OTEL_SCOPE } else { "user" }
$WriteConfig = $true
$Refresh = $false
$InstallType = if ($env:CLAUDE_OTEL_INSTALL_TYPE) { $env:CLAUDE_OTEL_INSTALL_TYPE } else { "gtrace" }
$ConfigFile = if ($env:GTRACE_CONFIG_FILE) { $env:GTRACE_CONFIG_FILE } else { Join-Path $HOME ".claude\gtrace.json" }
$Endpoint = if ($env:GTRACE_ENDPOINT) { $env:GTRACE_ENDPOINT } else { $env:CLAUDE_OTEL_ENDPOINT }
$TracePath = if ($env:GTRACE_TRACE_PATH) { $env:GTRACE_TRACE_PATH } else { $env:CLAUDE_OTEL_TRACE_PATH }
$MetricsPath = if ($env:GTRACE_METRICS_PATH) { $env:GTRACE_METRICS_PATH } else { $env:CLAUDE_OTEL_METRICS_PATH }
$XToken = if ($env:GTRACE_X_TOKEN) { $env:GTRACE_X_TOKEN } else { $env:X_TOKEN }
$TimeoutMs = if ($env:GTRACE_TIMEOUT_MS) { $env:GTRACE_TIMEOUT_MS } else { $env:CLAUDE_OTEL_TIMEOUT_MS }
$UserId = if ($env:GTRACE_USER_ID) { $env:GTRACE_USER_ID } else { $env:CLAUDE_OTEL_USER_ID }
$MaxChars = if ($env:GTRACE_MAX_CHARS) { $env:GTRACE_MAX_CHARS } else { $env:CLAUDE_OTEL_MAX_CHARS }
$DebugValue = if ($env:GTRACE_DEBUG) { $env:GTRACE_DEBUG } else { $env:CLAUDE_OTEL_DEBUG }
$EnabledValue = $env:CLAUDE_OTEL_ENABLED
$Headers = @()
$Tags = @()

function Write-InstallLog([string]$Message) {
    Write-Host "[install] $Message"
}

function Show-Usage {
    @"
Usage:
  .\scripts\install.ps1 [marketplace-source] [options]

Examples:
  .\scripts\install.ps1 . --endpoint https://llm-openway.guance.com --x-token <token>
  .\scripts\install.ps1 GuanceCloud/claude-otel-plugin --type gtrace --tag env=prod

Options:
  --refresh               Reinstall the plugin even if it already exists.
  --scope SCOPE           Claude plugin install scope. Default: user.
  --type TYPE             Config preset. Default: gtrace. Values: gtrace, otlp.
  --endpoint URL          Receiver base URL.
  --x-token TOKEN         Dataway/GTrace X-Token.
  --trace-path PATH       Trace route override.
  --metrics-path PATH     Metrics route override.
  --header KEY=VALUE      Extra HTTP header. Can be repeated.
  --tag KEY=VALUE         resourceAttributes entry. Can be repeated.
  --timeout-ms N          OTLP HTTP timeout in milliseconds.
  --user-id VALUE         user_id field attached to exported data.
  --max-chars N           Maximum captured characters.
  --debug                 Enable hook debug logging.
  --no-debug              Disable hook debug logging.
  --enabled BOOL          Enable or disable the hook. Values: true, false.
  --config-file PATH      Config file. Default: ~\.claude\gtrace.json.
  --no-config             Install plugin only; do not update gtrace.json.
  -h, --help              Show help.
"@
}

function Normalize-Bool([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    switch ($Value.Trim().ToLowerInvariant()) {
        { $_ -in @("1", "true", "yes", "on") } { return "true" }
        { $_ -in @("0", "false", "no", "off") } { return "false" }
        default { throw "Invalid boolean value: $Value" }
    }
}

function Normalize-Type([string]$Value) {
    switch ($Value.Trim().ToLowerInvariant()) {
        "gtrace" { return "gtrace" }
        "otlp" { return "otlp" }
        "otel" { return "otlp" }
        default { throw "Unsupported --type: $Value. Supported values: gtrace, otlp" }
    }
}

function Require-Value([string]$Option, [int]$Index, [object[]]$Values) {
    if ($Index -ge $Values.Count) { throw "$Option requires a value" }
    return [string]$Values[$Index]
}

function Split-Option([string]$Argument) {
    $position = $Argument.IndexOf("=")
    if ($position -lt 0) { return $null }
    return @($Argument.Substring(0, $position), $Argument.Substring($position + 1))
}

$arguments = @($args)
for ($i = 0; $i -lt $arguments.Count; $i++) {
    $argument = [string]$arguments[$i]
    $split = Split-Option $argument
    $option = if ($split) { $split[0] } else { $argument }
    $inlineValue = if ($split) { $split[1] } else { $null }

    switch ($option) {
        { $_ -in @("--refresh", "--reinstall") } { $Refresh = $true; continue }
        "--scope" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $Scope = $inlineValue; continue
        }
        "--type" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $InstallType = Normalize-Type $inlineValue; continue
        }
        "--endpoint" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $Endpoint = $inlineValue; continue
        }
        "--x-token" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $XToken = $inlineValue; continue
        }
        "--trace-path" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $TracePath = $inlineValue; continue
        }
        "--metrics-path" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $MetricsPath = $inlineValue; continue
        }
        "--header" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $Headers += $inlineValue; continue
        }
        "--tag" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $Tags += $inlineValue; continue
        }
        "--timeout-ms" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $TimeoutMs = $inlineValue; continue
        }
        "--user-id" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $UserId = $inlineValue; continue
        }
        "--max-chars" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $MaxChars = $inlineValue; continue
        }
        "--debug" { $DebugValue = "true"; continue }
        "--no-debug" { $DebugValue = "false"; continue }
        "--enabled" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $EnabledValue = Normalize-Bool $inlineValue; continue
        }
        "--config-file" {
            if ($null -eq $inlineValue) { $i++; $inlineValue = Require-Value $option $i $arguments }
            $ConfigFile = $inlineValue; continue
        }
        "--no-config" { $WriteConfig = $false; continue }
        { $_ -in @("-h", "--help") } { Show-Usage; exit 0 }
        default {
            if ($argument.StartsWith("--")) { throw "Unknown argument: $argument" }
            if (-not $MarketplaceSourceWasSet) {
                $MarketplaceSource = $argument
                $MarketplaceSourceWasSet = $true
            } else {
                throw "Unexpected positional argument: $argument"
            }
        }
    }
}

$InstallType = Normalize-Type $InstallType
if (-not [string]::IsNullOrWhiteSpace($EnabledValue)) { $EnabledValue = Normalize-Bool $EnabledValue }

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { throw "claude CLI not found in PATH" }
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required to run the hook. Install it from https://astral.sh/uv/"
}

if ([string]::IsNullOrWhiteSpace($TracePath)) {
    $TracePath = if ($InstallType -eq "gtrace") { "v1/write/otel-llm" } else { "v1/traces" }
}
if ([string]::IsNullOrWhiteSpace($MetricsPath)) {
    $MetricsPath = if ($InstallType -eq "gtrace") { "v1/write/otel-metrics" } else { "v1/metrics" }
}

$manifest = Join-Path $MarketplaceSource ".claude-plugin\marketplace.json"
if (Test-Path -LiteralPath $manifest) {
    & claude plugin validate $MarketplaceSource
    if ($LASTEXITCODE -ne 0) { throw "Plugin validation failed" }
}

$headerPairs = @()
if ($InstallType -eq "gtrace") { $headerPairs += "to_headless=true" }
if (-not [string]::IsNullOrWhiteSpace($XToken)) { $headerPairs += "X-Token=$XToken" }
$headerPairs += $Headers

$resourceAttributes = [ordered]@{}
foreach ($item in $Tags) {
    $position = $item.IndexOf("=")
    if ($position -le 0) { continue }
    $key = $item.Substring(0, $position).Trim()
    $value = $item.Substring($position + 1).Trim()
    if ($key -and $value) { $resourceAttributes[$key] = $value }
}

$pluginConfigArgs = @()
function Add-PluginConfig([string]$Key, [string]$Value) {
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        $script:pluginConfigArgs += @("--config", "$Key=$Value")
    }
}

Add-PluginConfig "CLAUDE_OTEL_ENABLED" $EnabledValue
Add-PluginConfig "OTEL_EXPORTER_OTLP_ENDPOINT" $Endpoint
Add-PluginConfig "CLAUDE_OTEL_TRACE_PATH" $TracePath
Add-PluginConfig "CLAUDE_OTEL_METRICS_PATH" $MetricsPath
Add-PluginConfig "OTEL_EXPORTER_OTLP_HEADERS" ($headerPairs -join ",")
if ($resourceAttributes.Count -gt 0) {
    Add-PluginConfig "CLAUDE_OTEL_RESOURCE_ATTRIBUTES" ($resourceAttributes | ConvertTo-Json -Compress)
}
Add-PluginConfig "CLAUDE_OTEL_DEBUG" $DebugValue
Add-PluginConfig "CLAUDE_OTEL_MAX_CHARS" $MaxChars
Add-PluginConfig "CLAUDE_OTEL_TIMEOUT_MS" $TimeoutMs
Add-PluginConfig "CLAUDE_OTEL_USER_ID" $UserId

function ConvertTo-Hashtable($Value) {
    if ($null -eq $Value) { return $null }
    if ($Value -is [System.Collections.IDictionary]) {
        $result = [ordered]@{}
        foreach ($key in $Value.Keys) { $result[[string]$key] = ConvertTo-Hashtable $Value[$key] }
        return $result
    }
    if ($Value -is [pscustomobject]) {
        $result = [ordered]@{}
        foreach ($property in $Value.PSObject.Properties) { $result[$property.Name] = ConvertTo-Hashtable $property.Value }
        return $result
    }
    if (($Value -is [System.Collections.IEnumerable]) -and -not ($Value -is [string])) {
        return @($Value | ForEach-Object { ConvertTo-Hashtable $_ })
    }
    return $Value
}

function Expand-UserPath([string]$Path) {
    if ($Path -eq "~") { return $HOME }
    if ($Path.StartsWith("~\") -or $Path.StartsWith("~/")) { return Join-Path $HOME $Path.Substring(2) }
    return [Environment]::ExpandEnvironmentVariables($Path)
}

function Write-GtraceConfig {
    $path = Expand-UserPath $ConfigFile
    $config = [ordered]@{}
    if (Test-Path -LiteralPath $path) {
        $raw = [IO.File]::ReadAllText($path)
        if (-not [string]::IsNullOrWhiteSpace($raw)) {
            $config = ConvertTo-Hashtable ($raw | ConvertFrom-Json)
        }
    }
    if ($null -eq $config) { $config = [ordered]@{} }

    if (-not [string]::IsNullOrWhiteSpace($EnabledValue)) {
        $config["enabled"] = $EnabledValue -eq "true"
    } elseif (-not $config.Contains("enabled")) {
        $config["enabled"] = $true
    }
    if ($Endpoint) { $config["endpoint"] = $Endpoint }
    if ($TracePath) { $config["tracePath"] = $TracePath }
    if ($MetricsPath) { $config["metricsPath"] = $MetricsPath }

    $configHeaders = if ($config.Contains("headers") -and $config["headers"] -is [System.Collections.IDictionary]) { $config["headers"] } else { [ordered]@{} }
    if ($InstallType -eq "gtrace" -and -not $configHeaders.Contains("to_headless")) { $configHeaders["to_headless"] = "true" }
    if ($XToken) { $configHeaders["X-Token"] = $XToken }
    foreach ($item in $Headers) {
        $position = $item.IndexOf("=")
        if ($position -le 0) { continue }
        $key = $item.Substring(0, $position).Trim()
        $value = $item.Substring($position + 1).Trim()
        if ($key -and $value) { $configHeaders[$key] = $value }
    }
    if ($configHeaders.Count -gt 0) { $config["headers"] = $configHeaders }

    $configTags = if ($config.Contains("resourceAttributes") -and $config["resourceAttributes"] -is [System.Collections.IDictionary]) { $config["resourceAttributes"] } else { [ordered]@{} }
    foreach ($key in $resourceAttributes.Keys) { $configTags[$key] = $resourceAttributes[$key] }
    if ($configTags.Count -gt 0) { $config["resourceAttributes"] = $configTags }

    if ($TimeoutMs) { $config["timeout_ms"] = [int]$TimeoutMs }
    if ($MaxChars) { $config["max_chars"] = [int]$MaxChars }
    if ($UserId) { $config["user_id"] = $UserId }
    if ($DebugValue) { $config["debug"] = (Normalize-Bool $DebugValue) -eq "true" }

    $parent = Split-Path -Parent $path
    if ($parent) { [IO.Directory]::CreateDirectory($parent) | Out-Null }
    $json = ($config | ConvertTo-Json -Depth 20) + [Environment]::NewLine
    [IO.File]::WriteAllText($path, $json, [Text.UTF8Encoding]::new($false))
    return $path
}

$hasInstallConfig = $EnabledValue -or $Endpoint -or $XToken -or $TimeoutMs -or $UserId -or $MaxChars -or $DebugValue -or $Headers.Count -gt 0 -or $Tags.Count -gt 0
$expandedConfigFile = Expand-UserPath $ConfigFile
if ($WriteConfig) {
    if ($hasInstallConfig -or (Test-Path -LiteralPath $expandedConfigFile)) {
        $writtenPath = Write-GtraceConfig
        Write-InstallLog "updated $writtenPath"
    } else {
        Write-InstallLog "skipped gtrace.json because no install-time config was provided"
    }
} else {
    Write-InstallLog "skipped gtrace.json because --no-config was set"
}

& claude plugin marketplace add $MarketplaceSource *> $null
& claude plugin marketplace update $MarketplaceName *> $null

$pluginList = (& claude plugin list --json 2>$null | Out-String)
if ($Refresh -or $pluginList.Contains($PluginId)) {
    & claude plugin uninstall $PluginId *> $null
}

& claude plugin install --scope $Scope @pluginConfigArgs $PluginId
if ($LASTEXITCODE -ne 0) { throw "Plugin installation failed" }

@"
Plugin installed.

Source: $MarketplaceSource
Scope: $Scope

Next step:
- Restart Claude Code to apply the updated plugin.
"@
