$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'
$model = Join-Path $repoRoot '.venv\Lib\site-packages\basic_pitch\saved_models\icassp_2022\nmp'

if (-not (Test-Path -LiteralPath $python)) {
    throw 'Missing .venv. Follow the Windows Basic Pitch setup in README.md.'
}
& $python -c "import sys; assert sys.version_info[:2] == (3, 11), 'Use Python 3.11 for this tested runtime'"
if ($LASTEXITCODE -ne 0) { throw 'Python runtime check failed.' }
if (-not (Test-Path -LiteralPath (Join-Path $model 'saved_model.pb'))) {
    throw 'Missing Basic Pitch SavedModel. Install backend/requirements-windows.lock.txt.'
}

$env:SETUPTOOLS_USE_DISTUTILS = 'local'
$env:PIANO_TRANSCRIBER_RUNNER_MODE = 'basic-pitch'
$env:PIANO_TRANSCRIBER_AUTO_RUN_TRANSCRIPTIONS = '1'
$env:PIANO_TRANSCRIBER_BASIC_PITCH_MODEL_PATH = $model
$env:PIANO_TRANSCRIBER_DATA_DIR = Join-Path $repoRoot 'backend\data'
$env:PYTHONUNBUFFERED = '1'

Write-Host "Runner: basic-pitch; model: $model"
Write-Host "Persistent data: $env:PIANO_TRANSCRIBER_DATA_DIR"
& $python -m uvicorn app.main:app --app-dir (Join-Path $repoRoot 'backend') --host 127.0.0.1 --port 8000 --loop asyncio --http h11
if ($LASTEXITCODE -ne 0) { throw "Backend stopped with exit code $LASTEXITCODE" }
