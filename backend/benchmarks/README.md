# Onafhankelijke MIDI-baseline

## Definitieve richting na MAPS en capdiagnose

ByteDance blijft primary voor de stagedemo met menselijke correctie en bekende
offsetbeperking. De synthetische baseline hieronder is historisch onderzoeksbewijs.
De latere [MAPS-validatie](maps/maps-enstdkcl-validation.md) ondersteunt betere
pitch/onset-detectie op die subset, maar trager CPU-gedrag en beperkte note ends.
Policy B/C: **DO NOT SHIP**. [Capdiagnose](maps/maps-long-note-cap-diagnosis.md):
**KEEP CURRENT CAP**. Geen policies in productie; geen nieuw onderzoek nodig
om de huidige checkpointbeslissing vast te leggen. Scripts/fixtures blijven
bruikbaar als offline regressie-infrastructuur.

Deze benchmark verandert niets aan engines, thresholds, fallback, canonical
schema of editor. ByteDance blijft primair. Beide bestaande adapters draaien via
dezelfde echte upload/job/artifact-API; predictions worden nooit gecorrigeerd.

Er waren geen onafhankelijke MIDI/audio-paren in de repository. De twee echte
piano-WAVs hebben geen performance-MIDI; bestaande job-MIDI's zijn modeloutput.
De bestaande demo is sinusaudio. Die is niet geschikt voor deze pianobaseline.

Vier nieuwe handgeschreven MIDI-plannen worden vóór inferentie vastgelegd door
`prepare.py`: single_notes (4), melody_repeated (8), overlapping_chords (6) en
long_notes_sustain (5). Dit is 23 onafhankelijke note-on/key-release-events,
waarvan de laatste fixture CC64 bevat. Ze zijn geen modelafgeleide labels.

Audio wordt synthetisch gerenderd met de reeds geïnstalleerde
`pretty_midi/TimGM6mb.sf2` en de officiële portable FluidSynth 2.5.6. Dit is geen
bewijs voor microfoonopnames. Renderer en SoundFont worden niet aan Git toegevoegd.
FluidSynth asset SHA-256 wordt bij download gecontroleerd; input/model/runtimehashes
worden per benchmark vastgelegd. Eén onafhankelijke rerender is byte-identiek bewezen.

## Mappen

- `backend/data/ground_truth/fixtures/`: vier kleine `.mid` files, metadata en
  `baseline-manifest.json`; geschikt om later bewust aan Git toe te voegen.
- `backend/data/ground_truth/rendered/`: reproduceerbare WAVs, gitignored.
- `backend/data/benchmarks/runs/<run>/ground_truth/` en `audio/`: snapshots.
- `.../predictions/bytedance/` en `.../predictions/basic_pitch/`: originele
  canonical JSON, MIDI en jobmetadata per clip.
- `.../reports/`: CSV, Markdown, per-clip fouten, summary en environment.

Voor de eerste baseline: `backend/data/benchmarks/runs/20261006-baseline-01/reports/`.
Alle bestaande lokale modeldata en worktreewijzigingen blijven behouden.

## Herhalen op de bestaande Windows-machine

`<repo>` in voorbeelden is jouw checkoutpad, geen vast lokaal gebruikerspad.

Er zijn geen nieuwe Python-dependencies nodig: mir_eval 0.8.2, mido 1.3.3,
pretty_midi 0.2.11.post0, NumPy 1.26.4 en SoundFile zijn al geïnstalleerd via de
bestaande locks. Gebruik dezelfde Python 3.11.9-omgeving en beide huidige modellen.

Eenmalig/inputs controleren, vanuit PowerShell:

```powershell
Set-Location '<repo>'
& .\scripts\setup-benchmark-renderer.ps1
$env:PYTHONPATH = 'backend'
& .\.venv\Scripts\python.exe -m benchmarks.prepare
```

`prepare` overschrijft geen bestaande baseline: afwijkende hashes geven een fout.
Ontbrekende WAVs worden uit de bevroren MIDI gerenderd en moeten dezelfde hash
hebben. De noteplannen, gain (0.2), 44.1 kHz stereo PCM16, GM piano program 0,
chorus/reverb uit en geen normalisatie zijn vastgezet. MIDI-keyrelease is niet
hetzelfde als het einde van de SoundFont-release/resonantie. WAVs bevatten tail.

Backend in een afzonderlijke terminal:

```powershell
Set-Location '<repo>'
& .\scripts\start-bytedance.ps1
```

Benchmark (de frontend hoeft niet te draaien):

```powershell
Set-Location '<repo>'
$env:PYTHONPATH = 'backend'
& .\.venv\Scripts\python.exe -m benchmarks.run
```

Dit kiest een nieuwe timestampmap. `--output` kan een nog niet bestaande map
selecteren. Een bestaande run wordt nooit overschreven. Elke WAV wordt één keer
geüpload; beide engines gebruiken dezelfde upload. Demo-resultaten, corrected
artifacts, mislukte jobs of gewijzigde inputs worden niet als baseline geaccepteerd.
Geen automatische latencycorrectie, noise, filtering of engineparameterwijziging.

## Scoring

Primaire `TP/FP/FN`, `precision/recall/F1` zijn **pitch én onset**. mir_eval gebruikt
maximum-cardinality één-op-één bipartite matching; onset <=50 ms, zelfde integer
MIDI-pitch (1 cent tolerantie in Hz-omzetting). Afstanden worden zoals in mir_eval
op 0.1 ms afgerond; `strict=False`. Geen offsetvereiste in de primaire score.

De CSV vermeldt daarnaast expliciet pitch-only en onset-only TP/FP/FN/P/R/F1:

- pitch-only vergelijkt aantallen events per pitch, zonder timing;
- onset-only matcht timing binnen 50 ms zonder pitch;
- offset-F1 vereist bovendien offsetafstand <=max(50 ms, 20% reference-nootduur).

Onset MAE/mediaan en offset MAE/bias worden over primaire matches gemeten.
Ground-truth keyrelease en CC64-effective release worden apart gehouden.
Velocity-MAE gebruikt bekende MIDI note-on commands alleen voor ByteDance;
Basic Pitch-velocity is een amplitudeproxy. Velocity verandert geen score.
Totals zijn microaggregaties, geen gemiddelde van clip-F1's.

Foutdiagnostiek onderscheidt correcte matches, gelijke pitch met verkeerde
timing, verkeerde pitch bij nabije onset, gemist en extra. Residuele pairing is
heuristisch en verandert nooit de officiële scores. Volledige events worden
opgeslagen voor handmatige inspectie **na** scoring.

De baseline geeft geen algemene modelrangschikking. Vervolg: onafhankelijke
MIDI/audio van een echte piano toevoegen en dezelfde scoring hergebruiken.

## Tests

```powershell
& .\.venv\Scripts\python.exe -m pytest -q backend/tests/test_benchmark_metrics.py
```

Tests controleren tempo, velocity-zero note-off, CC64/reattack, één-op-één
matching, 50 ms grens, verkeerde pitch versus timing, offsets apart,
lege/mislukte reference-noten en microaggregatie. De volledige backendset had
128 passed en één reeds bestaande Windows-fout (oversized upload file lock).
De parallelle TestClient-startup/idempotencytest faalde in de eerste run maar
slaagde in de laatste run; deze bestaande flaky test is niet aangepast.
Alle 15 benchmarktests slagen, inclusief frozen-fixture-hashbewaking en herstel.
