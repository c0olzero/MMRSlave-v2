# Builds dist\MMRSlave\MMRSlave.exe and dist\MMRSlave-windows-<commit>.zip.
# Uses its own environment (.venv-build) with the CPU-only build of PyTorch, so the app stays
# a few hundred MB instead of several GB with the CUDA build used for training.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$py = Join-Path $root ".venv-build\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating the build environment (.venv-build)..."
    $base = if (Get-Command py -ErrorAction SilentlyContinue) { "py -3.14" } else { "python" }
    Invoke-Expression "$base -m venv .venv-build"
    & $py -m pip install --upgrade pip
    & $py -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    & $py -m pip install . pyinstaller
    # The app's own code ships as plain files, not as an installed package.
    & $py -m pip uninstall -y mmrslave
}
& $py packaging\build.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
