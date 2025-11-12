Param(
    [string]$Python = "python",
    [string]$Venv = ".venv-build",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

function Write-Step($Message) {
    Write-Host "==> $Message"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if ($Clean -and (Test-Path $Venv)) {
    Write-Step "Removing existing virtualenv $Venv"
    Remove-Item -Recurse -Force $Venv
}

$PythonCmd = Get-Command $Python -ErrorAction SilentlyContinue
if (-not $PythonCmd) {
    throw "Python executable '$Python' not found. Install Python 3 and ensure it is on PATH."
}

if (-not (Test-Path $Venv)) {
    Write-Step "Creating virtualenv $Venv"
    & $PythonCmd.Source -m venv $Venv
}

$VenvPython = Join-Path $Venv "Scripts/python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Virtualenv python not found at $VenvPython"
}

Write-Step "Upgrading pip"
& $VenvPython -m pip install --upgrade pip | Out-Host

Write-Step "Installing dependencies and PyInstaller"
& $VenvPython -m pip install -r requirements.txt pyinstaller | Out-Host

Write-Step "Building standalone executable with PyInstaller"
& $VenvPython -m PyInstaller --onefile auto_follow.py --name auto_follow | Out-Host

$DistDir = Join-Path $ScriptDir "dist"
if (Test-Path $DistDir) {
    $SampleConfig = Join-Path $DistDir "channels.sample.json"
    Write-Step "Copying channels.json to $SampleConfig"
    Copy-Item -Path (Join-Path $ScriptDir "channels.json") -Destination $SampleConfig -Force
}

Write-Step "Build complete. Executable is located at dist\auto_follow.exe"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  - Edit dist\channels.sample.json (or provide your own) before running."
Write-Host "  - Ensure ffmpeg.exe is available in PATH or copied beside auto_follow.exe."
Write-Host "  - Run: dist\auto_follow.exe --config channels.sample.json --download-dir C:\path\to\downloads"

