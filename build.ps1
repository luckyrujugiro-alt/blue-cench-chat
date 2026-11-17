# Builds BlueCenchChat.exe and, when Inno Setup 6 is installed, the installer.
# Usage (PowerShell, from the project folder):   .\build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

Write-Host "`n== Running tests ==" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed - not building." }

Write-Host "`n== Building BlueCenchChat.exe ==" -ForegroundColor Cyan
& .\.venv\Scripts\pyinstaller.exe bluecenchchat.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
Write-Host "Application: dist\BlueCenchChat\BlueCenchChat.exe"

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    Write-Host "`n== Building installer ==" -ForegroundColor Cyan
    & $iscc installer\bluecenchchat.iss
    Write-Host "Installer: dist\BlueCenchChat-Setup-1.0.0.exe"
} else {
    Write-Host "`nInno Setup 6 was not found. Install it from https://jrsoftware.org/isdl.php and run this script again to get the installer." -ForegroundColor Yellow
}
