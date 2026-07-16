$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

$Repo = if ($env:CLAUDE_OTEL_REPO) { $env:CLAUDE_OTEL_REPO } else { "GuanceCloud/claude-otel-plugin" }
$Ref = if ($env:CLAUDE_OTEL_REF) { $env:CLAUDE_OTEL_REF } else { "main" }
$RawBaseUrl = if ($env:CLAUDE_OTEL_RAW_BASE_URL) { $env:CLAUDE_OTEL_RAW_BASE_URL } else { "https://raw.githubusercontent.com/$Repo/$Ref" }
$arguments = @($args)

if ($arguments.Count -gt 0 -and $arguments[0] -in @("-h", "--help")) {
    @"
Usage:
  install-remote.ps1 [install options]

Example:
  & ([scriptblock]::Create((Invoke-RestMethod https://raw.githubusercontent.com/GuanceCloud/claude-otel-plugin/main/scripts/install-remote.ps1))) ``
      --endpoint https://llm-openway.guance.com --x-token <token>

Install options are passed to scripts/install.ps1.
"@
    exit 0
}

$tempDir = Join-Path ([IO.Path]::GetTempPath()) ("claude-otel-plugin-" + [guid]::NewGuid().ToString("N"))
$installScript = Join-Path $tempDir "install.ps1"
[IO.Directory]::CreateDirectory($tempDir) | Out-Null

try {
    Invoke-WebRequest -UseBasicParsing -Uri "$RawBaseUrl/scripts/install.ps1" -OutFile $installScript
    & $installScript $Repo @arguments
    if ($LASTEXITCODE -ne 0) { throw "Plugin installation failed" }
} finally {
    if (Test-Path -LiteralPath $tempDir) { Remove-Item -LiteralPath $tempDir -Recurse -Force }
}
