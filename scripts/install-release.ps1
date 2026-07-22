$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Repo = "GuanceCloud/claude-otel-plugin"
$arguments = @($args)
$VersionInput = "latest"
if ($arguments.Count -gt 0 -and -not ([string]$arguments[0]).StartsWith("--")) {
    $VersionInput = [string]$arguments[0]
    $arguments = @($arguments | Select-Object -Skip 1)
}

if ($VersionInput -in @("-h", "--help") -or ($arguments.Count -gt 0 -and $arguments[0] -in @("-h", "--help"))) {
    @"
Usage:
  install-release.ps1 [latest|vX.Y.Z|X.Y.Z] [install options]

Example:
  & ([scriptblock]::Create((Invoke-RestMethod https://github.com/GuanceCloud/claude-otel-plugin/releases/latest/download/install-release.ps1))) latest ``
      --endpoint https://llm-openway.guance.com --x-token <token>

Install options are passed to scripts/install.ps1.
"@
    exit 0
}

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { throw "claude CLI not found in PATH" }
if (-not (Get-Command uv -ErrorAction SilentlyContinue) -and -not (Get-Command python3 -ErrorAction SilentlyContinue)) {
    throw "Either uv or python3 is required to run the hook. Preferred: install uv from https://astral.sh/uv/ . Fallback: ensure python3 with venv support is available on PATH."
}
if (-not (Get-Command tar -ErrorAction SilentlyContinue)) { throw "tar not found in PATH" }

function Normalize-Tag([string]$Version) {
    if ($Version -eq "latest") { return "latest" }
    if ($Version.StartsWith("claude-otel-plugin--v")) { return $Version }
    if ($Version.StartsWith("v")) { return "claude-otel-plugin--$Version" }
    return "claude-otel-plugin--v$Version"
}

$tag = Normalize-Tag $VersionInput
$baseUrl = if ($tag -eq "latest") {
    "https://github.com/$Repo/releases/latest/download"
} else {
    "https://github.com/$Repo/releases/download/$tag"
}

$tempDir = Join-Path ([IO.Path]::GetTempPath()) ("claude-otel-plugin-" + [guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $tempDir "claude-otel-plugin.tar.gz"
$checksumPath = Join-Path $tempDir "claude-otel-plugin.tar.gz.sha256"
$installRoot = Join-Path $HOME ".claude\marketplaces\claude-otel-plugin-release"
[IO.Directory]::CreateDirectory($tempDir) | Out-Null

try {
    $archiveUrl = "$baseUrl/claude-otel-plugin.tar.gz"
    Invoke-WebRequest -UseBasicParsing -Uri $archiveUrl -OutFile $archivePath

    $checksumAvailable = $true
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/claude-otel-plugin.tar.gz.sha256" -OutFile $checksumPath
    } catch {
        $checksumAvailable = $false
        Write-Warning "Checksum asset is unavailable; continuing without checksum verification."
    }
    if ($checksumAvailable) {
        $expected = ([IO.File]::ReadAllText($checksumPath)).Trim().Split(" ")[0].ToLowerInvariant()
        $actual = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($expected -and $actual -ne $expected) { throw "checksum verification failed for $archiveUrl" }
    }

    & tar -C $tempDir -xzf $archivePath
    if ($LASTEXITCODE -ne 0) { throw "Failed to extract release package" }

    $packageDir = Join-Path $tempDir "claude-otel-plugin"
    if (-not (Test-Path -LiteralPath (Join-Path $packageDir ".claude-plugin\marketplace.json"))) {
        throw "release package is missing .claude-plugin/marketplace.json"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $packageDir "scripts\install.ps1"))) {
        throw "release package is missing scripts/install.ps1"
    }

    if (Test-Path -LiteralPath $installRoot) { Remove-Item -LiteralPath $installRoot -Recurse -Force }
    [IO.Directory]::CreateDirectory((Split-Path -Parent $installRoot)) | Out-Null
    Copy-Item -LiteralPath $packageDir -Destination $installRoot -Recurse

    & (Join-Path $installRoot "scripts\install.ps1") $installRoot --refresh @arguments
    if ($LASTEXITCODE -ne 0) { throw "Plugin installation failed" }
} finally {
    if (Test-Path -LiteralPath $tempDir) { Remove-Item -LiteralPath $tempDir -Recurse -Force }
}
