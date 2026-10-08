$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$model = Join-Path $repoRoot 'backend\data\models\CRNN_note_F1=0.9677_pedal_F1=0.9186.pth'
if (-not (Test-Path -LiteralPath $python)) { throw 'Missing .venv. Follow README.md.' }
& $python -c "import sys; assert sys.version_info[:2] == (3, 11), 'Use the tested Python 3.11 runtime'"
if ($LASTEXITCODE -ne 0) { throw 'Python runtime check failed.' }
if (-not (Test-Path -LiteralPath $model)) { throw 'Missing checkpoint. Run scripts/setup-bytedance.ps1.' }
if ((Get-FileHash -LiteralPath $model -Algorithm MD5).Hash -ne '22B961B77C1878239FEC963362097045') {
    throw 'Checkpoint checksum differs from Zenodo record 4034264.'
}
$env:PIANO_TRANSCRIBER_RUNNER_MODE = 'bytedance'
$env:PIANO_TRANSCRIBER_AUTO_RUN_TRANSCRIPTIONS = '1'
$env:PIANO_TRANSCRIBER_BYTEDANCE_MODEL_PATH = $model
$env:PIANO_TRANSCRIBER_DATA_DIR = Join-Path $repoRoot 'backend\data'
$env:PYTHONUNBUFFERED = '1'
$env:SETUPTOOLS_USE_DISTUTILS = 'local'
$env:MPLCONFIGDIR = Join-Path $repoRoot 'backend\data\model-cache\matplotlib'
Write-Host "Primary engine: ByteDance; device: CPU; checkpoint: $model"
& $python -m uvicorn app.main:app --app-dir (Join-Path $repoRoot 'backend') --host 127.0.0.1 --port 8000 --loop asyncio --http h11
if ($LASTEXITCODE -ne 0) { throw "Backend stopped with exit code $LASTEXITCODE" }
