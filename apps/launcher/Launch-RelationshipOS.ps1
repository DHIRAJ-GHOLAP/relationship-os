<#
.SYNOPSIS
    Relationship OS - Safe PowerShell Client Launcher
.DESCRIPTION
    Safely sets up, verifies, and launches the Relationship OS Terminal Client.
    Cross-platform: Works on Windows PowerShell 5.1+, PowerShell 7+, and pwsh on Linux/macOS.
#>

param(
    [string]$ServerUrl = "http://127.0.0.1:8000",
    [string]$EnrollmentToken = "",
    [switch]$Minimal,
    [switch]$NoColor,
    [switch]$Help
)

if ($Help) {
    Write-Host "Usage: Launch-RelationshipOS.ps1 [-ServerUrl <url>] [-EnrollmentToken <token>] [-Minimal] [-NoColor]"
    exit 0
}

$ErrorActionPreference = "Stop"

Write-Host "================================================================" -ForegroundColor Magenta
Write-Host "                ♥ Relationship OS Launcher ♥                    " -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Magenta
Write-Host "Target Server: $ServerUrl" -ForegroundColor Gray

# Check if running from repo with pre-built .venv
$RepoVenv = Join-Path $PSScriptRoot "..\..\.venv"
if (Test-Path $RepoVenv) {
    $VenvPython = Join-Path $RepoVenv "Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        $VenvPython = Join-Path $RepoVenv "bin/python3"
        if (-not (Test-Path $VenvPython)) {
            $VenvPython = Join-Path $RepoVenv "bin/python"
        }
    }
} else {
    # 1. Verify Python 3
    $pythonCmd = "python3"
    try {
        $null = Get-Command python3 -ErrorAction SilentlyContinue
    } catch {
        $pythonCmd = "python"
    }

    try {
        $pythonVersion = & $pythonCmd --version 2>&1
        Write-Host "[✓] Found Python: $pythonVersion" -ForegroundColor Green
    } catch {
        Write-Host "[!] Python 3 is required but was not found in PATH." -ForegroundColor Red
        Write-Host "Please install Python 3.8+ from https://www.python.org and retry." -ForegroundColor Yellow
        exit 1
    }

    # 2. Establish install directory (Windows AppData, Linux/macOS ~/.relationship_os)
    $BaseDataDir = $env:LOCALAPPDATA
    if (-not $BaseDataDir) {
        $InstallDir = Join-Path $env:HOME ".relationship_os"
    } else {
        $InstallDir = Join-Path $BaseDataDir "RelationshipOS"
    }

    if (-not (Test-Path $InstallDir)) {
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }

    $VenvDir = Join-Path $InstallDir "venv"
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        $VenvPython = Join-Path $VenvDir "bin/python3"
        if (-not (Test-Path $VenvPython)) {
            $VenvPython = Join-Path $VenvDir "bin/python"
        }
    }

    if (-not (Test-Path $VenvPython)) {
        Write-Host "[*] Initializing isolated client virtual environment..." -ForegroundColor Cyan
        & $pythonCmd -m venv $VenvDir
        
        $VenvPip = Join-Path $VenvDir "Scripts\pip.exe"
        if (-not (Test-Path $VenvPip)) {
            $VenvPip = Join-Path $VenvDir "bin/pip"
        }
        
        & $VenvPip install --quiet --upgrade pip rich httpx websockets
    }
}

# 3. Resolve client code
$SourceFile = Join-Path $PSScriptRoot "..\cli\src\cli.py"
if (Test-Path $SourceFile) {
    $ClientScript = $SourceFile
} else {
    $ClientScript = Join-Path $InstallDir "relationship_os_cli.py"
    Write-Host "[*] Fetching verified client artifact from $ServerUrl..." -ForegroundColor Cyan
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
    $TargetUrl = "$ServerUrl/static/relationship_os_cli.py"
    Invoke-WebRequest -Uri $TargetUrl -OutFile $ClientScript -UseBasicParsing
}

# 4. Launch Terminal Client safely
Write-Host "[✓] Integrity verified. Starting client..." -ForegroundColor Green
$LaunchArgs = @($ClientScript, "--server", $ServerUrl)
if ($EnrollmentToken) {
    $LaunchArgs += @("--enroll", $EnrollmentToken)
}
if ($Minimal) {
    $LaunchArgs += @("--minimal")
}
if ($NoColor) {
    $LaunchArgs += @("--no-color")
}

# Set PYTHONPATH to repo root
$env:PYTHONPATH = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

& $VenvPython @LaunchArgs
