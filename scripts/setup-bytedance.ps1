$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Create the Python 3.11 .venv as documented in README.md first.' }
& $python -m pip install 'torch==2.7.1' --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch install failed.' }
& $python -m pip install -r (Join-Path $repoRoot 'backend\requirements-bytedance-windows.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'ByteDance dependencies install failed.' }
& $python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed.' }
$modelDir = Join-Path $repoRoot 'backend\data\models'
New-Item -ItemType Directory -Force $modelDir | Out-Null
$model = Join-Path $modelDir 'CRNN_note_F1=0.9677_pedal_F1=0.9186.pth'
if (-not (Test-Path -LiteralPath $model)) {
    $download = "$model.download"
    Invoke-WebRequest 'https://zenodo.org/api/records/4034264/files/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth/content' -OutFile $download
    if ((Get-FileHash -LiteralPath $download -Algorithm MD5).Hash -ne '22B961B77C1878239FEC963362097045') {
        throw 'Downloaded model checksum mismatch; incomplete file was not published.'
    }
    Move-Item -LiteralPath $download -Destination $model
}
if ((Get-FileHash -LiteralPath $model -Algorithm MD5).Hash -ne '22B961B77C1878239FEC963362097045') {
    throw 'Existing checkpoint checksum mismatch.'
}
Write-Host 'ByteDance CPU runtime and official checkpoint ready.'
