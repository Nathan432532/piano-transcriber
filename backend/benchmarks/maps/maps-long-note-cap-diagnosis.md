# MAPS: diagnose van de zes-seconden-cap

8 oktober 2026. Beslissing: **KEEP CURRENT CAP**. Geen productieadapter/dependency gewijzigd; geen thresholds, offsetpeakregel, onset/pitch-/pedaallogica of Policy B/C toegepast. De cap is een echte decoderlimiet, maar verhogen/verwijderen is op deze data geen verdedigbare kleine productiefix.

## Root cause en timing

GeÃ¯nstalleerd `piano-transcription-inference==0.0.6`: `.venv/Lib/site-packages/piano_transcription_inference/piano_vad.py`, functie `note_detection_with_onset_offset_regress`, regel 64. De exacte conditie:

```python
if bgn and (i - bgn >= 600 or i == onset_output.shape[0] - 1):
```

De decoder schrijft dan een event op frame i en wist bgn/frame_disappear/offset_occur. Dit is een harde letterlijke constante, geen configureerbare adapterwaarde. De cap wordt gecontroleerd na de bestaande frame-disappearance/offset-midpointregel. Een volgende onset sluit de vorige noot eerder af op iâˆ’1. Een onset op frame 0 wordt door upstream truthiness anders behandeld; dat gedrag is bewust niet gerepareerd in dit experiment.

Werkelijke configuratie: `config.py:1,6` heeft sample_rate=16000, frames_per_second=100. `models.py:159â€“161,178` berekent hop_size=16000//100=160 samples en gebruikt die als spectrogramhop. Dus **160/16000=0,010 s/frame**, en **600Ã—0,010=6,000 s**. `utilities.py:401â€“402` converteert events via `(frame + regression_shift)/100`; de uiteindelijke eventduur is `6 + (offset_shiftâˆ’onset_shift)/100`, daarom ongeveer zes seconden. Bij het gemeten geval pitch 31 is beginframe 51, endframe 651, onsetshift âˆ’0,428922 en offsetshift 0: duur 6,004289 s vÃ³Ã³r float32-eventconversie.

## Historische reden

Een aparte read-only upstream checkout toont dat de 600-conditie al aanwezig is in de eerste commit [9300eaa, 6 mei 2020](https://github.com/qiuqiangkong/piano_transcription_inference/commit/9300eaab2feb1b0a8f97009a5d436b0db133ca2b). `git log -S 600`, de vier commits die piano_vad.py wijzigden, blame en broncomments geven geen keuzeonderbouwing. Het enige comment bij deze tak is â€˜Offset not detectedâ€™. Ook de README en 24 beschikbare upstream issue/PR-bodies leveren geen verklaring voor precies zes seconden. **reason unknown**. Niet bewezen dat het een workaround voor segmentgrenzen is. De huidige [upstream bron](https://github.com/qiuqiangkong/piano_transcription_inference/blob/master/piano_transcription_inference/piano_vad.py) heeft dezelfde conditie.

## Audio â†’ model â†’ decoder â†’ canonical

Audio wordt door de bestaande binding met librosa naar 16 kHz mono omgezet. Lange input krijgt overlappende modelsegmenten; de modelheads worden vervolgens gedeframed tot Ã©Ã©n tijdreeks. EÃ©n nootdecoder per pitch loopt over die samengevoegde tijdreeks. De cap is dus **decoder-only en onafhankelijk van een individuele segmentlengte**. Op de cap staat frameactivatie bij de vier lange matches nog duidelijk boven 0,1 (circa 0,714â€“0,988); het netwerk is daar nog actief. Geen echte offset is vereist voor de cap-stop.

De bestaande adapter verandert de upstream end niet wanneer die binnen audio ligt; hij clipt uitsluitend ends voorbij echte audioduur en laat starts buiten echte audio weg. De canonical JSON bevat daarom dezelfde te vroege cap-end. In het experiment is dezelfde bestaande `normalize_bytedance_notes` gebruikt, zonder wijzigingen.

## Segmentatie en gevonden tweede beperking

`inference.py:18,77â€“94,125â€“173`: segment_samples=160000, dus 10 s; enframe-hop=80000, dus 5 s en 50% overlap. Audio wordt met nullen tot een veelvoud van 10 s gepad. Elk segment krijgt een eigen model-forward, zonder GRU-hidden-state-overdracht. De framehead conditioneert mede op onset/offsetheads (`models.py:242â€“246`). Segment B start op 5 s en bevat de oorspronkelijke onset rond 0,5 s dus niet. Het effect daarvan is hier observationeel vastgesteld; een causale modelablatietest is niet uitgevoerd.

Deframe verwijdert bij meerdere segmenten hun laatste center=True-frame. Het bewaart frames 0â€“749 uit segment 0, frames 250â€“749 uit middensegmenten en frames 250â€“999 uit het laatste segment. **Geen averaging, blending of nootstitching**: joins op globale frames 750,1250,1750,... (7,5/12,5/17,5 s). De decoderstate wordt daar niet gereset; een noot kan technisch over joins blijven bestaan, mits de geselecteerde heads actief blijven.

Op drie lange MAPS-noten is dat niet het geval. Op hetzelfde fysieke tijdstip 7,5 s levert segment 0 nog frameactivatie >0,1, terwijl segment 1 vrijwel nul levert. Deframe schakelt naar segment 1 en veroorzaakt een frame-disappearance-stop op exact 7,5 s zodra de cap die niet eerder afbreekt:

| Case/pitch | Framehead segment 0 @7,5s | Framehead segment 1 @7,5s | Nocap decoder stop |
|---|---|---|---|
| 07_long/82 | 0.473689109 | 0.000000116 | frame 750: frame_disappearance |
| 08_long/62 | 0.665430009 | 0.001441335 | frame 750: frame_disappearance |
| 09_long/31 | 0.963052273 | 0.005276634 | frame 750: frame_disappearance |

Grafiek: `experiments/long_note_cap/results/segment-frame-activation.png` (relatief aan dit rapport).

Modeloutput na zes seconden is aanwezig: 2000/3000 samengevoegde frames voor de langere clips. Maar aanwezigheid van output betekent niet dat de framehead de aangehouden noot blijft herkennen. Bij pitch 31 is ook een latere offsetpeak op 17,225 s aanwezig; die kan de al op 7,5 s beÃ«indigde noot niet herstellen. De oorspronkelijke 18,05 s noot heeft dus zowel een capprobleem als een segment/model-headprobleem.

Verder blijft `inference.py:94` `[0:audio_len]` gebruiken met **samples** als slice-index op een **frame**-matrix. Daardoor blijft gepadde output meestal aanwezig: 1001 frames bij Ã©Ã©n segment en 2000/3000 bij langere clips. Dit bestaande probleem is hier alleen beschreven, niet gerepareerd. De adapterclips blijven exact gelijk.

## Offline varianten en targeted gate

Lokale decoderreproductie onder `experiments/long_note_cap/decoder.py`; alleen maximum decoderduur verschilt. A=600 frames, cap-variant B=1200, C=3000, D=None. **Cap-variant B is niet de eerder verworpen offset Policy B.** Geen upstream monkeypatch; geen modelinferentie; geen herbinning of thresholdtuning. De cached accepted peaks/shifts/frameheads blijven onveranderd.

3000 frames is gekozen als beschikbare-output-bovengrens van deze bevroren cache, niet uit GT-release: maximaal 3000 frames. C kan op deze input geen vroege duurcap triggeren en is daarom bounded-equivalent aan D. Ook D heeft de bestaande finite-array-loop en last-frame-stop; geen oneindige zoeklus. Op langere toekomstige input zijn B/C/D niet equivalent.

Targeted eerst: 01_isolated, 02_isolated, 04_isolated, 05_long, 06_long, 07_long, 08_long, 09_long, 10_repeated, 13_sustain, 16_chords. De normale controls, repeated, sustain en akkoord zijn unchanged; drie long-matches verbeteren enigszins en Ã©Ã©n verslechtert. Dat is technisch plausibel voor een volledige **risicocontrole**, niet voldoende voor productiegoedkeuring. Daarna exact dezelfde 24 frozen cases. Manifest SHA256 `eb6560e2f7306400a6f561bb6f615709fb20cb722fea801cc3a29ff968b021c1`.

A wordt op alle 88 pitches van iedere clip exact vergeleken met de geÃ¯nstalleerde upstreamdecoder, de gecachete library-events en canonical JSON. Ook raw-segmentheads â†’ upstream deframe â†’ cached matrices is bit-exact gecontroleerd. Alle package-/adapter-/model-/audio-/artifact-hashes zijn gevalideerd. Geen ground truth beschikbaar in de decoderfunctie; labels worden pas na globale decoding gekoppeld voor scoring en traces.

## Alle vijf lange noten

Endtijden in seconden op dezelfde raw MIDI-tijdlijn (geen shifts). â€˜Beste foutâ€™ hieronder is slechts diagnostiek van de vier vooraf gekozen globale regels; er wordt geen per-noot policy gekozen.

| Case | Pitch | GT duur | GT onset | GT key end | A end | B end | C end | D end | Beste abs fout s |
|---|---|---|---|---|---|---|---|---|---|
| 05_long | 105 | 3.587 | 0.517 | 4.104 | â€” | â€” | â€” | â€” | FN in alle varianten |
| 06_long | 95 | 5.537 | 0.523 | 6.060 | 6.520 | 7.662 | 7.662 | 7.662 | 0.460 |
| 07_long | 82 | 8.078 | 0.517 | 8.595 | 6.510 | 7.500 | 7.500 | 7.500 | 1.095 |
| 08_long | 62 | 11.994 | 0.514 | 12.508 | 6.500 | 7.500 | 7.500 | 7.500 | 5.008 |
| 09_long | 31 | 18.049 | 0.514 | 18.563 | 6.510 | 7.500 | 7.500 | 7.500 | 11.063 |

Pitch 105 wordt door alle varianten gemist; andere voorspelde pitches blijven FP. Pitch 95 verslechtert van 460 ms te laat naar 1602 ms te laat; upstream loopt door tot 10 s padded sequence-end en canonical clipt op 7,662 s. Pitches 82/62/31 winnen slechts ongeveer Ã©Ã©n seconde en eindigen alsnog te vroeg op de segmentjoin. **Geen lange match krijgt een release binnen Â±50 ms.**

## Long-note traces en normale controls

Targeted-summary.json bevat alle matched noottraces voor alle varianten: GT onset/key/pedal/duration, audio duration, decoderframes/shifts/reason, canonical end/clipping, offsetpeaks en frame-/offsethead-observaties. De ontbrekende pitch 105 staat als FN in targeted/full-notes.csv. Hieronder de vier cap-matches plus twee redelijk gedecodeerde normale controls; key=pedal bij deze S0-cases.

| Case/pitch | GT onset/key/pedal | GT duur/audio duur | Raw onset | Begin/endframe | Raw end/canonical | Reden / clipping | Activatie @cap | Accepted peaks na onset |
|---|---|---|---|---|---|---|---|---|
| 01_isolated/36 | 0.516996/2.518998/2.518998 | 2.002002/4.121000 | 0.510762 | 51/250 | 2.504899/2.504899 | offset_peak_after_midpoint / False | 0.018 | [2.504899] |
| 02_isolated/60 | 0.519987/2.521989/2.521989 | 2.002002/4.127000 | 0.522625 | 52/255 | 2.550000/2.550000 | frame_disappearance / False | 0.003 | [0.563202, 2.555953] |
| 06_long/95 | 0.522991/6.059999/6.059999 | 5.537008/7.662000 | 0.515250 | 52/652 | 6.520000/6.520000 | maximum_duration_cap / False | 0.988 | [] |
| 07_long/82 | 0.516996/8.594983/8.594983 | 8.077987/10.198000 | 0.509668 | 51/651 | 6.510000/6.510000 | maximum_duration_cap / False | 0.714 | [] |
| 08_long/62 | 0.513992/12.507994/12.507994 | 11.994002/14.109063 | 0.498082 | 50/650 | 6.500000/6.500000 | maximum_duration_cap / False | 0.763 | [0.542391] |
| 09_long/31 | 0.513992/18.562991/18.562991 | 18.048999/20.165000 | 0.505711 | 51/651 | 6.510000/6.510000 | maximum_duration_cap / False | 0.974 | [17.224831] |

## Full MAPS replay

Een-op-Ã©Ã©n gelijke MIDI-pitch, onset â‰¤50 ms; offsets apart, bestaande MAPS evaluator/mir_eval. Elke variant heeft exact dezelfde **541 TP / 139 FP / 44 FN**, precision 0,795588, recall 0,924786, F1 0,855336; onset-MAE **13,083 ms**. Pitch/start/velocity/confidence zijn op volledige canonical lijsten identiek gecontroleerd. Alleen vijf canonical ends wijzigen: vier TP en Ã©Ã©n FP, uitsluitend in long-cases.

| Metric | A_600 | B_1200 | C_3000 | D_no_cap |
|---|---|---|---|---|
| Key MAE ms | 301.831 | 298.433 | 298.433 | 298.433 |
| Key mediaan ms | 117.111 | 117.111 | 117.111 | 117.111 |
| Key max ms | 12052.990 | 11062.991 | 11062.991 | 11062.991 |
| Effective MAE ms | 148.474 | 145.077 | 145.077 | 145.077 |
| Effective mediaan ms | 50.980 | 50.980 | 50.980 | 50.980 |
| Effective max ms | 12052.990 | 11062.991 | 11062.991 | 11062.991 |
| >250 ms | 161 | 161 | 161 | 161 |
| >500 ms | 97 | 98 | 98 | 98 |
| >1 s | 36 | 37 | 37 | 37 |
| Early >50 ms | 75 | 75 | 75 | 75 |
| Late >50 ms | 270 | 270 | 270 | 270 |
| Scored end exact audio | 5 | 6 | 6 | 6 |
| Upstream end beyond audio, all real starts | 19 | 20 | 20 | 20 |
| Canonical beyond audio | 0 | 0 | 0 | 0 |

| Categorie | Key MAE A / B,C,D ms | Key mediaan A / B,C,D ms | Key max A / B,C,D ms | Effective MAE A / B,C,D ms |
|---|---|---|---|---|
| chords | 50.740 / 50.740 | 7.573 / 7.573 | 403.994 / 403.994 | 50.740 / 50.740 |
| isolated | 435.045 / 435.045 | 60.009 / 60.009 | 1606.063 / 1606.063 | 435.045 / 435.045 |
| long | 5151.492 / 4691.992 | 4046.488 / 3304.997 | 12052.990 / 11062.991 | 5151.492 / 4691.992 |
| music | 283.730 / 283.730 | 141.840 / 141.840 | 2679.080 / 2679.080 | 110.071 / 110.071 |
| repeated | 74.449 / 74.449 | 24.051 / 24.051 | 1668.991 / 1668.991 | 74.449 / 74.449 |
| sustain | 701.837 / 701.837 | 128.033 / 128.033 | 1853.014 / 1853.014 | 600.499 / 600.499 |

## Actief gecontroleerde regressies

- **Normal/repeated/sustain/chords/music:** canonical noten en ends blijven op alle geselecteerde cases identiek. Next-onset sluit eerdere same-pitch noten nog steeds op het voorafgaande frame; geen nieuw doorlopen over een volgende onset. Pitches worden onafhankelijk gedecodeerd; geen nieuwe koppeling tussen akkoordnoten. Dit is bewijs voor deze subset, geen garantie voor alle audio.
- **Long pitch 95:** nieuwe duidelijke regressie: end 6,520â†’7,662 s, absolute key/effective-fout 0,460â†’1,602 s. Frameactivatie blijft zelfs op 10 s padded output 0,981. Geen geaccepteerde offset; langer laten doorlopen maakt spurious sustained activation riskanter.
- **False positive pitch 74 in 08_long:** ongewenste duur 6,500â†’7,500 s; de FP-count blijft gelijk maar de extra noot wordt Ã©Ã©n seconde langer. Dit telt niet mee in matched offset-MAE en is daarom expliciet vermeld.
- **Long pitch 82/62/31:** beperkt beter, maar nieuwe stop is de framehead-discontinuÃ¯teit bij 7,5 s. Drie fouten blijven 1,095/5,008/11,063 s te vroeg. Een hogere cap herstelt geen ontbrekende modelactivatie.
- **Audio-end:** upstream-events voorbij echte audio 19â†’20 (alle echte starts, inclusief muziekcontext na scorevenster), scored canonical grensends 5â†’6; canonical nooit voorbij audio door ongewijzigde clipping. Dit is geen bewijs dat die clips correcte releases hebben.
- **Eerder correcte matches:** geen door deze capvarianten nieuw beschadigde correcte Â±50 ms-release op deze subset. De Ã©Ã©n al foute lange noot en verlengde FP zijn wel relevante regressies; meer fouten >500 ms (97â†’98) en >1 s (36â†’37).
- **Ruis:** geen nieuwe gecontroleerde noise-inferentie uitgevoerd; cached spurious activations/FP en deterministische persistent-headtests laten het mechanisme zien. Een capvrij decoderpad kan op langere input doorgaan tot beschikbare output stopt; dat is begrensd maar geen kwaliteitsgarantie.

Full-changes.csv vermeldt alle vijf veranderde noten voor elk van B/C/D; full-results.csv geeft per case alle metrics en flags. targeted/full-notes.csv bewaart TP/FN/FP afzonderlijk. De oude MAPS-resultaten zijn niet overschreven.

## Stagedemo-aanbeveling en maximaal drie opties

**KEEP CURRENT CAP.** De huidige cap veroorzaakt een zichtbare fout, maar simpel verhogen verwijdert die niet: een gemiddeld voordeel van slechts **3,397 ms** overall en een nog steeds 11,063 s fout op de langste noot, tegenover een nieuwe >1 s releasefout en een langere FP. Dat is geen veilige, merkbare productverbetering voor een demo met menselijke correctie.

1. **Cap behouden** â€” kleinste/veiligste huidige keuze. Bekende duurbeperking documenteren en handmatig corrigeren. Geen codewijziging nodig.
2. **Cap verhogen via een expliciete lokale decoderwrapper** â€” kleiner dan herontwerp, maar nu afgewezen door regressie en resterende segmentfouten. De library biedt geen instelling: alleen een extra adapterparameter is technisch onvoldoende. Niet als productexperiment aanbevelen op huidig bewijs.
3. **Begrensd vervolgonderzoek naar segmentheads/deframing en decodercontinuÃ¯teit** â€” ingrijpender; eerst offline bewijs verzamelen rond 7,5 s joins voordat een lokale wrapper of wijziging van samenvoegen wordt overwogen. Geen garantie dat alleen een decoderwijziging de ontbrekende frameactivatie kan herstellen. Geen grote refactor of productiewijziging nu.

De kleinste verdedigbare productiewijziging op dit bewijs is **geen runtimewijziging**. Als verder onderzoek gewenst is, is het nieuwe gerichte probleem de segmenthead-discrepantie, niet de constante geÃ¯soleerd. Policy B blijft verworpen; Policy C is niet gebruikt.

## Tests, runtime en reproduceren

60 relevante tests: nieuwe captests (13), MAPS, ByteDance-adapter, bestaande offsetdiagnostiek en matcher. Drie bestaande deprecationwarnings. Tests omvatten korte noot, exacte capgrens/stopvolgorde, lange noot, next-onset, persistent activation, finite-output-stop, adapterclipping, joins zonder decoderreset, echte deframe-chunkselectie, onafhankelijke akkoordpitches en actual-upstream-baseline-equivalentie op deterministische random heads.

Geen modelinferentie uitgevoerd. Targeted replay 51.1 s; full replay 107.7 s inclusief cachehashes, decoding, scoring en raw-deframeverificatie. Dit zijn offline analysetijden, geen productinference-latenties.

Vanuit backend, met dezelfde bestaande Python 3.11-venv en ongewijzigde externe MAPS-cache:

```powershell
$capRoot = '<MAPS-root>\ENSTDkCl'
$capCache = '<MAPS-root>\evaluation-20261007'
$capOutput = 'benchmarks/maps/experiments/long_note_cap/results'
& '..\.venv\Scripts\python.exe' -m benchmarks.maps.experiments.long_note_cap.run --dataset-root $capRoot --cache $capCache --output $capOutput --stage targeted
if ($LASTEXITCODE -ne 0) { throw 'Targeted replay failed' }
& '..\.venv\Scripts\python.exe' -m benchmarks.maps.experiments.long_note_cap.run --dataset-root $capRoot --cache $capCache --output $capOutput --stage full
if ($LASTEXITCODE -ne 0) { throw 'Full replay failed' }
& '..\.venv\Scripts\python.exe' -m benchmarks.maps.experiments.long_note_cap.report --output $capOutput
```

297 bestaande repo-/dependency-/cachebestanden zijn vooraf met SHA256 beschermd. Definitieve controle en volledige git-status worden naast dit rapport geleverd. Dataset/ZIP/WAV/MIDI zijn niet toegevoegd aan de repo. Alle toevoegingen zijn experimentele code, tests en nieuwe rapportartefacten. Geen commit/stage/push, geen productie- of dependencypatch.
