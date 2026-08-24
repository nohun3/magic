$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing project virtual environment: $python"
}

Push-Location $projectRoot
try {
    $stagingRoot = Join-Path $projectRoot "build\release"
    $workRoot = Join-Path $projectRoot "build\pyinstaller"
    & $python -m PyInstaller --noconfirm --clean `
        --distpath $stagingRoot --workpath $workRoot STM200.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }

    $releaseDir = Join-Path $stagingRoot "STM200"
    $zipPath = Join-Path $projectRoot "dist\STM200-win64.zip"
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }
    Compress-Archive -Path (Join-Path $releaseDir "*") -DestinationPath $zipPath
    Write-Host "Release folder: $releaseDir"
    Write-Host "Release archive: $zipPath"
}
finally {
    Pop-Location
}
