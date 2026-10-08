# Offline offset-policy-experiment

> Afgesloten onderzoek: Policy B en C zijn **DO NOT SHIP** als algemene fixes.
> De oorspronkelijke synthetische resultaten hieronder blijven historisch bewijs.
> De latere MAPS-validatie toont schadelijke B-regressies; de bestaande cap blijft
> behouden. Zie `../../maps/maps-enstdkcl-validation.md` en
> `../../maps/maps-long-note-cap-diagnosis.md`. Geen productie-import aanbevolen.

Geen productie-imports van deze policies; geen adapterwijziging, upstreampatch,
thresholdtuning, nieuwe audio, correcties of jobs. Vier bestaande bevroren clips,
23 MIDI-referentienoten. Regels vooraf vastgelegd, vóór scoring.

## Vastgelegde regels

- **A:** exacte upstream events, gevolgd door de bestaande adapterclip
  `min(offset, resampled_audio_duration)`. CSV bewaart ook de ongeclipte upstream
  offset. Zo reproduceert A de oorspronkelijke canonical baseline precies.
- **B:** eerste upstream geaccepteerde offsetpiek na de nootonset, niet later dan
  de huidige upstream end of echte audioduur, en strikt vóór de volgende onset
  van dezelfde pitch. Gebruik `offset_output` en de bestaande parabolische shift;
  geen eigen lokale maxima, nieuwe threshold of gewijzigde piekfilter.
  Upstream gebruikt offsetthreshold 0.3 en monotonic neighbour=4. Een piek binnen
  een **voorspeld** pedaalinterval wordt overgeslagen, niet verplaatst naar pedal-up.
  Geen bruikbare piek: A behouden. Andere pitches begrenzen dit venster niet.
- **D:** herken `six_second_cap` of `sequence_end` uit dezelfde decoderstate,
  gecontroleerd tegen upstream. Behoud normale beslissingen. Alleen als de
  native WAV in alle kanalen eindigt met exacte digitale nullen, begrens een
  boundary-note tot het eerste sample na het laatste niet-nul sample. Dit moet
  na de onset en vóór A liggen. Geen amplitude-epsilon, vaste nootduur of
  minimaal aantal stiltesamples. Anders alleen signaleren en A behouden.
- **C:** B indien een bruikbare piek bestaat; anders D (die zonder bewijs A behoudt).

De guard geeft een globale bovengrens aan hoorbaar signaal, geen nauwkeurige
key-release of pitchspecifieke akoestische offset. Bij ruisrijke echte opnames
zal hij meestal abstineren. Een decodergrens herkennen bewijst op zichzelf niet
dat een lange noot fout is. Een geaccepteerde modelpiek is ook geen garantie dat
het pedaal correct wordt begrepen.

## Reproduceren (PowerShell vanuit repositoryroot)

```powershell
$env:SETUPTOOLS_USE_DISTUTILS = 'local'
$env:MPLCONFIGDIR = "$PWD\backend\data\model-cache\matplotlib"
Set-Location backend
..\.venv\Scripts\python.exe -m benchmarks.experiments.offset_policy.run --collect-missing
..\.venv\Scripts\python.exe -m pytest tests/test_offset_policies.py tests/test_benchmark_metrics.py tests/test_bytedance_adapter.py tests/test_offset_diagnostics.py -q
```

`--collect-missing` voert uitsluitend inferentie uit voor historische clips
waarvan raw heads nog ontbreken. Reeds opgeslagen diagnoseheads worden gekopieerd.
Dezelfde model-SHA en audio-SHA zijn vereist; canonical noten moeten exact gelijk
zijn aan `20261006-baseline-01` voordat ze gescoord mogen worden.

Na de eerste run is uitsluitend cache nodig:

```powershell
..\.venv\Scripts\python.exe -m benchmarks.experiments.offset_policy.run
```

Cache met modelheads, upstreamevents en herkomsthashes staat gitignored onder
`backend/data/benchmarks/runs/offset-policy-frozen-heads/`. Referentie-MIDI wordt
pas geopend nadat **alle** policybeslissingen berekend zijn. Alleen scoring matcht
notes via de bestaande mir_eval pitch/onset-matcher (50 ms, één-op-één).

CSV en machineleesbare resultaten worden geschreven onder
`backend/benchmarks/reports/`. Alle CSV-tijden/fouten zijn seconden; fouten zijn
getekend `prediction - reference`. MAE/mediaan/max in het rapport zijn milliseconden.
Key release en CC64-verlengde release worden afzonderlijk gescoord. MIDI-releases
zijn geen onafhankelijke annotaties van het einde van akoestische resonantie.

Het Markdownrapport bevat de interpretatie van deze ene bevroren run en wordt
niet automatisch herschreven bij herhaling. Er is geen wetenschappelijk bewijs
van generalisatie met vier synthetische clips en slechts drie sustainnoten.
