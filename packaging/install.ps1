# NewDoAuto Zero-Dependency Per-User Installer Script
# Installs NewDoAuto to %LOCALAPPDATA%\Programs\NewDoAuto without requiring administrator privileges.

param(
    [switch]$AddToPath = $true,
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\NewDoAuto"
)

$ErrorActionPreference = "Stop"

Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host "         NewDoAuto Windows Installer (Per-User)            " -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir
$distExe = Join-Path $rootDir "dist\newdoauto.exe"
$distGuiExe = Join-Path $rootDir "dist\NewDoAuto-Desktop.exe"

if (-not (Test-Path $distExe)) {
    Write-Error "dist\newdoauto.exe not found! Please run packaging/build_standalone.py first."
}

Write-Host "Installing to: $InstallDir" -ForegroundColor Green
$binDir = Join-Path $InstallDir "bin"
$wfDir = Join-Path $InstallDir "workflows"

New-Item -ItemType Directory -Force -Path $binDir | Out-Null
New-Item -ItemType Directory -Force -Path $wfDir | Out-Null

Copy-Item $distExe -Destination (Join-Path $binDir "newdoauto.exe") -Force
if (Test-Path $distGuiExe) {
    Copy-Item $distGuiExe -Destination (Join-Path $binDir "NewDoAuto-Desktop.exe") -Force
}
Copy-Item (Join-Path $rootDir "workflows\*") -Destination $wfDir -Force
Copy-Item (Join-Path $rootDir "README.md") -Destination $InstallDir -Force
Copy-Item (Join-Path $rootDir ".env.example") -Destination $InstallDir -Force

$installedExe = Join-Path $binDir "newdoauto.exe"
Write-Host "Installed executable to: $installedExe" -ForegroundColor Green

if ($AddToPath) {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$binDir*") {
        Write-Host "Adding $binDir to user PATH..." -ForegroundColor Yellow
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$binDir", "User")
        $env:Path = "$env:Path;$binDir"
    } else {
        Write-Host "$binDir is already present in user PATH." -ForegroundColor Gray
    }
}

Write-Host "`nVerifying installation..." -ForegroundColor Cyan
& $installedExe --version

Write-Host "`nInstallation completed successfully!" -ForegroundColor Green
Write-Host "Run 'newdoauto run <workflow.json>' from your terminal to automate Windows." -ForegroundColor White
