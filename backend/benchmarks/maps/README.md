# Frozen MAPS ENSTDkCl benchmark (offline only)

This directory extends the existing benchmark matcher and decoder diagnostics.
It does not change the app, engines, decoder, model thresholds or correction flow.
Review `maps-enstdkcl-validation.md` first. The committed-intended manifest is the
authoritative frozen selection; do not delete/reselect it after seeing results.

## Existing environment

Run from the repository's `backend` directory with the existing Python 3.11.9
`.venv`. This machine already has both models and dependencies. No new packages
were installed for this benchmark: piano-transcription-inference 0.0.6,
torch 2.7.1+cpu, torchlibrosa 0.1.0, basic-pitch 0.4.0, tensorflow 2.15.0,
numpy 1.26.4, librosa 0.11.0, soundfile 0.14.0, mir_eval 0.8.2, mido and psutil.
For a fresh machine consult the existing project setup documentation and
`scripts/setup-bytedance.ps1`; inference requires the existing ByteDance checkpoint
in `backend/data/models` and the Basic Pitch packaged TensorFlow model.

## Download only ENSTDkCl

The official release is https://zenodo.org/records/18160555 (0.4).
Read its licence before redistributing recordings: CC-BY-NC-SA 2.0 FR.
Replace `<repo>` with your checkout directory and `<MAPS-root>` with an external
dataset directory (for example under your own user profile), never inside Git.
Keep ZIP, recordings, source MIDI and inference cache outside the repository.
PowerShell example, using a task-specific variable instead of a system variable:

```powershell
$mapsDir = '<MAPS-root>'
New-Item -ItemType Directory -Force -Path $mapsDir | Out-Null
curl.exe --location --fail --retry 6 --retry-delay 5 --continue-at - `
  --output "$mapsDir\ENSTDkCl.zip" `
  'https://zenodo.org/api/records/18160555/files/ENSTDkCl.zip/content'
if ($LASTEXITCODE -ne 0) { throw 'Download failed; rerun to resume' }
if ((Get-Item -LiteralPath "$mapsDir\ENSTDkCl.zip").Length -ne 2608287080) {
  throw 'Wrong ENSTDkCl archive size'
}
if ((Get-FileHash -LiteralPath "$mapsDir\ENSTDkCl.zip" -Algorithm MD5).Hash.ToLowerInvariant() `
    -ne '72bbdf40eb7af69225755e165a0a0a08') { throw 'Wrong ENSTDkCl checksum' }
# First extraction only; the archive contains its own ENSTDkCl directory.
if (-not (Test-Path -LiteralPath "$mapsDir\ENSTDkCl")) {
  Expand-Archive -LiteralPath "$mapsDir\ENSTDkCl.zip" -DestinationPath "$mapsDir\ENSTDkCl"
}
```

The resulting root is `...\MAPS\ENSTDkCl\ENSTDkCl`; both the outer and inner
root are accepted. Approximately 6.46 GiB for archive + extracted payload,
plus external inference artifacts. No full MAPS release or MAESTRO is required.

## Verify, infer, score, report

```powershell
Set-Location '<repo>\backend'
$mapsRoot = '<MAPS-root>\ENSTDkCl'
$mapsRun = '<MAPS-root>\evaluation-20261007'

# Existing frozen manifest: checks source SHA256; never reselects its cases.
& '..\.venv\Scripts\python.exe' -m benchmarks.maps.dataset --dataset-root $mapsRoot
if ($LASTEXITCODE -ne 0) { throw 'Frozen data verification failed' }

# Sequential processes, real unchanged production adapters, CPU defaults.
# Identical existing cache is replayed; changed identity aborts.
& '..\.venv\Scripts\python.exe' -m benchmarks.maps.infer `
  --dataset-root $mapsRoot --output $mapsRun --engine bytedance
if ($LASTEXITCODE -ne 0) { throw 'ByteDance run failed' }
& '..\.venv\Scripts\python.exe' -m benchmarks.maps.infer `
  --dataset-root $mapsRoot --output $mapsRun --engine basic_pitch
if ($LASTEXITCODE -ne 0) { throw 'Basic Pitch run failed' }

# No inference, no app job, no demo runner, no production offset policy.
& '..\.venv\Scripts\python.exe' -m benchmarks.maps.evaluate `
  --dataset-root $mapsRoot --output $mapsRun
if ($LASTEXITCODE -ne 0) { throw 'Offline scoring failed' }
& '..\.venv\Scripts\python.exe' -m benchmarks.maps.report `
  --dataset-root $mapsRoot --output $mapsRun
if ($LASTEXITCODE -ne 0) { throw 'Report failed' }
```

For new inference use a **new** external `$mapsRun`, preserving the original run.
The chosen source WAV/MIDI/TXT, windows and labels stay fixed. Predictions record
audio/model/adapter/upstream SHA256, package versions and CPU settings; modified
cached artifacts are rejected. ByteDance raw segmentheads, deframed heads and
upstream events are retained for offline traces; Basic Pitch canonical output
is retained. Music crops contain exact source PCM samples from [0,15)s; both
engines score only onsets in [0,10)s. No alignment shifts or noise edits.

Outputs in this directory: manifest, per-case/category/overall CSV, TP/FN/FP note
CSV, changed matched B-note CSV, compact review JSON and Markdown report.
Large summaries, prediction artifacts and source data remain under `$mapsRun`.
The report records the initial ASCII-order audit issue without changing the
already frozen music subset. A fresh selection with the corrected inspector
would differ, so keep the published manifest for reproducing this run.

## Tests

Use a fresh writable temp directory on Windows if the default pytest temp
directory has stale ownership/ACLs:

```powershell
$mapsTestTemp = Join-Path $env:TEMP ('piano-maps-tests-' + [guid]::NewGuid().ToString())
& '..\.venv\Scripts\python.exe' -m pytest tests/test_maps_benchmark.py `
  tests/test_benchmark_metrics.py tests/test_bytedance_adapter.py `
  tests/test_offset_policies.py --basetemp=$mapsTestTemp -q
```

Policy B is imported unchanged from the existing experiment and only its B
result is scored. No C/D benchmark or production policy is introduced. Counts
of new early notes use effective release; counts of previously correct key
releases cut early use physical note-off. These groups can overlap.
