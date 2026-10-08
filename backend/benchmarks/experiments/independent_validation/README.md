# Onafhankelijke offset-validatie

> Historische synthetische holdout, voorafgaand aan MAPS. De definitieve keuze is
> ByteDance primary met menselijke correctie en bekende offsetbeperking. Policy
> B/C: **DO NOT SHIP**; geen productieonderzoekskandidaat meer. Zie
> `../../maps/maps-enstdkcl-validation.md`. De oorspronkelijke evaluatieregels
> en meetresultaten blijven ongewijzigd.
>
> Volledige historische replay vereist ook de twee lokaal aangeleverde WAVs
> uit het bevroren manifest. Ze worden niet gebundeld: herkomst/licentie is
> onbevestigd. De modelvrije tests en MAPS-benchmark vereisen deze WAVs niet.

Validatie, geen productiefix. B/C worden geïmporteerd uit het eerdere experiment
en hun bron-SHA256 moet exact gelijk blijven:
`f6e1d8b8a311e0e23b2c84f9451b1aa91cf50758dafd267b45dca55e2446814e`.
Geen thresholds, adapter, dependency, frontend of schema wijzigen.

## Dataset vóór inferentie

Acht nieuwe MIDI-plannen, 17 unieke referentienoten:
drie lange nootcases (4, 5.5, 7.5 s), drie sustaincases (single, pair, reattack),
vijf herhaalde D4's en een akkoord met vier verschillende releases.
Geen van de oorspronkelijke vier benchmarkclips wordt gebruikt.

Twee vaste ruisvarianten kopiëren dezelfde MIDI van pedal_g4 en staggered_chord:
5 herhaalde referentie-events, geen 5 extra onafhankelijke labels.
Ruis: PCG64-seeds 20261007/20261008, onafhankelijke stereo Gaussian, lfilter
`[1]/[1,-0.97]`, RMS -70 dBFS per kanaal zonder signaalafhankelijke schaling.
WAV PCM24; clean is PCM16. Geen gainnormalisatie of modeltuning.

Twee bestaande pianoloops hebben geen onafhankelijke MIDI/akoestische herkomst;
ze worden alleen diagnostisch getranscribeerd, niet in accuracy opgenomen.
De gebruiker heeft bevestigd geen aanvullende echte akoestische opnames te
hebben. Die beperking verhindert een READY-conclusie over echte opnames.

Manifest en nieuwe MIDI's: `backend/data/ground_truth/fixtures/independent_validation/`.
Render-WAVs en twee isolated pair-stems:
`backend/data/ground_truth/rendered/independent_validation/` (gitignored).
Alle inputhashes en render-/ruisinstellingen staan in het bevroren manifest.
Stemextinctie is een onafhankelijke sample-level signaalbound, geen perceptueel
hoorbare eindtijd of policyinput. Key release en pedal-extended release komen
uitsluitend uit vooraf geschreven MIDI.

## Vaste veiligheidstoetsen

Vastgelegd in manifest vóór modelinferentie. Vroeg/correct/laat gebruikt de
bestaande 50 ms tolerance, strenger dan de onveranderde offset-F1-tolerance
`max(50 ms, 20% nootduur)`. Geen nieuwe modelthreshold.

- Een A-correcte lange noot door B/C >50 ms vóór key release afbreken: fail.
- Een vroege wijziging die sustain richting key release trekt en de fout
  tegenover pedal-release >50 ms vergroot: fail.
- Een gewijzigde offset >50 ms vóór de onafhankelijke effectieve release:
  fail, ook als A zelf niet perfect was. Ongewijzigde vroege A-offsets worden
  afzonderlijk als model/decoderprobleem gerapporteerd.
- Pitch/onset/count veranderen is een directe assertionfout.
- Verdwijnen van C-specifieke winst (C t.o.v. B) bij de vaste ruisvariant:
  guard werkt daar niet. Geen reparatie/tuning op deze validatieset.

Elk nootresultaat wordt afzonderlijk gerapporteerd; ontbrekende matches blijven
FN en extra predictions FP. Timingmetrics gelden uitsluitend voor gematchte
noten en kunnen daardoor gemiste lange noten niet verbergen.

## Reproduceren (PowerShell vanuit repositoryroot)

```powershell
$env:SETUPTOOLS_USE_DISTUTILS = 'local'
$env:MPLCONFIGDIR = "$PWD\backend\data\model-cache\matplotlib"
Set-Location backend
..\.venv\Scripts\python.exe -m benchmarks.experiments.independent_validation.prepare
..\.venv\Scripts\python.exe -m benchmarks.experiments.independent_validation.run --capture
..\.venv\Scripts\python.exe -m pytest tests/test_offset_policies.py tests/test_benchmark_metrics.py tests/test_bytedance_adapter.py tests/test_independent_validation.py -q
```

Prepare schrijft alleen een nieuwe dataset als er nog geen manifest bestaat;
een bestaand manifest wordt uitsluitend gecontroleerd. Dit voorkomt stilzwijgend
vervangen van de holdoutset. Bewaar de bevroren WAVs/cache voor exact dezelfde
replay. De bestaande portable FluidSynth 2.5.6, TimGM6mb.sf2 en modelcheckpoint
moeten aanwezig zijn. Er zijn geen nieuwe dependencies nodig.

`--capture` voert alleen ontbrekende echte inferenties uit met de ongewijzigde
productiebinding. Geen API-job, demo, correction-artifact of herinferentie op
bestaande caches. De cached raw segmentheads worden tegen de upstream deframe
gecontroleerd, ook voor de 7.5 s held note met meerdere segmenten.

Volgende runs zonder modelinitialisatie/inferentie:

```powershell
..\.venv\Scripts\python.exe -m benchmarks.experiments.independent_validation.run
```

Alle runtimebeslissingen worden berekend vóór de referentie-MIDI voor scoring
wordt gedecodeerd. Cache gitignored:
`backend/data/benchmarks/runs/independent-validation-heads/`.
Rapport, metrics-CSV, notes-CSV en resultaten-JSON:
`backend/benchmarks/reports/bytedance-offset-independent-validation*`.
CSV-tijden en signed fouten: seconden. MAE/mediaan/max: milliseconden.
Clean/noise worden apart geaggregeerd; diagnostische audio wordt nooit gescoord.
