# ByteDance: onafhankelijke offset-validatie

> Historische synthesevalidatie van vóór MAPS. De toenmalige B-verdicts hieronder
> zijn vervangen door **B DO NOT SHIP** op basis van echte Disklavier-data.
> C blijft **DO NOT SHIP**. Geen policy in productie. Definitieve enginekeuze:
> ByteDance + menselijke correctie + bekende offsetbeperking; **KEEP CURRENT CAP**.
> Zie `../maps/maps-enstdkcl-validation.md`. Historische metrics blijven intact.

Uitgevoerd: 2026-10-07T17:45:17.744882+00:00

**B: MORE VALIDATION NEEDED; C: DO NOT SHIP.** Geen policy in productie toegepast; geen thresholds/dependency/adapter/schema/frontend gewijzigd. Geen commit of push.

## Dataset

Acht nieuwe onafhankelijke MIDI-plannen, **17 unieke ground-truthnoten**. Twee vooraf gekozen ruisvarianten herhalen vijf referentie-events; dit zijn geen vijf extra onafhankelijke labels. Clean en noise worden apart gescoord. De oorspronkelijke 23-notenbenchmark is niet gebruikt als primaire validatie.
Twee bestaande piano-audioclips worden uitsluitend diagnostisch gebruikt. Hun akoestische/opnameherkomst is onbevestigd, onafhankelijke labels ontbreken, en de gebruiker heeft geen aanvullende echte akoestische opnames. Er is dus **geen bewezen verbetering op echte akoestische opnames**.

| Case | Soort | Categorie | GT-noten | Sustain | GT-bron |
|---|---|---|---|---|---|
| hold_c4_4s | synthetic/clean | long | 1 | nee | vooraf geschreven MIDI |
| hold_a4_55s | synthetic/clean | long | 1 | nee | vooraf geschreven MIDI |
| hold_e4_75s | synthetic/clean | long | 1 | nee | vooraf geschreven MIDI |
| pedal_g4 | synthetic/clean | sustain | 1 | ja | vooraf geschreven MIDI |
| pedal_pair | synthetic/clean | sustain | 2 | ja | vooraf geschreven MIDI |
| pedal_reattack | synthetic/clean | sustain | 2 | ja | vooraf geschreven MIDI |
| repeated_d4 | synthetic/clean | repeated | 5 | nee | vooraf geschreven MIDI |
| staggered_chord | synthetic/clean | overlap | 4 | nee | vooraf geschreven MIDI |
| pedal_g4_noise | synthetic/noise | sustain | 1 | ja | vooraf geschreven MIDI |
| staggered_chord_noise | synthetic/noise | overlap | 4 | nee | vooraf geschreven MIDI |
| 140_Cm_Piano_VKeys_02_268_2 | existing_audio_unverified_origin/existing | diagnostic | — | onbekend | geen; diagnostisch |
| 120_G_Offbeat_01_53_SP | existing_audio_unverified_origin/existing | diagnostic | — | onbekend | geen; diagnostisch |

Manifest bevroren vóór inferentie: 2026-10-07T17:27:24.188684+00:00. SHA256: `ba987cb7700c36379baf85b324a25a34ee3d224716c0ce272aea6a105606fd27`.
B/C exact dezelfde bron-SHA256 als vorige experiment: `f6e1d8b8a311e0e23b2c84f9451b1aa91cf50758dafd267b45dca55e2446814e`.
Manifest/MIDI: `backend/data/ground_truth/fixtures/independent_validation/`; WAVs: `backend/data/ground_truth/rendered/independent_validation/` (gitignored).
FluidSynth 2.5.6, dezelfde TimGM6mb.sf2, 44.1 kHz stereo PCM16, gain 0.2, chorus/reverb uit. Alle checksum- en rendercommando's zijn bevroren in manifest. Alle runtimebeslissingen worden berekend vóór de MIDI voor scoring wordt gedecodeerd. Geen prediction-afgeleide labels.
Voor sustain-pair bestaan onafhankelijke isolated stems voor sample-level signaalextinctie. Extinctie/laatste niet-nul sample is een bovenlimiet, **geen perceptuele annotatie van hoorbare note end**. Voor reattack/overlap kan de globale audio-extinctie niet aan één noot worden toegekend.

## Vaste policies en failcriteria

A: exacte upstream events plus bestaande adapterclipping aan resampled audioduur. B: eerste upstream geaccepteerde offsetpiek in het reeds vastgelegde eventvenster; voorspeld pedaalinterval blokkeert een piek tijdens sustain. C: B, of zonder bruikbare piek de vooraf bestaande boundary/exact-zero guard. Logica ongewijzigd, geen tuning op holdout.
Vroeg/correct/laat: bestaande **50 ms tolerance** voor veiligheid, zowel tegenover key als pedal-extended release. Dit is geen modelthreshold. Bestaande offset-F1 gebruikt onveranderd max(50 ms,20% duur). Offset-MAE en classificatie gelden alleen voor pitch/onset-matches; ontbrekende noten blijven zichtbaar als FN.

- releaseToleranceSeconds: 0.05
- long: Candidate changes an A-correct long note to end >50 ms before key release
- sustain: Candidate moves earlier towards key release while worsening pedal-release error by >50 ms
- repeated: Candidate changes pitch/onset/count, merges events or extends into the next same-pitch onset
- wrongPeak: Selected peak cuts before independently known release by >50 ms; report even if A was also wrong
- noise: C-specific (C vs B) benefit disappears when exact terminal silence is replaced by fixed low background noise
- decision: Any observed harmful premature change prevents READY; lack of verified real recordings also prevents READY

## Resultaten per categorie en totaal

TP/FP/FN en F1 hieronder vereisen pitch+onset. Onset-F1 afzonderlijk negeert pitch. Pitches/onsets/counts zijn exact gelijk voor A/B/C; assertions controleren dat. Key/effective-release-MAE zijn ms. Effective release is pedal-extended waar aanwezig, anders key release. Clean TOTAL=17 unieke referentienoten; noise TOTAL=5 kopie-events; all TOTAL=22 eventinstanties, niet 22 onafhankelijke labels.

| Groep | Policy | GT | TP/FP/FN | Note-F1 | Onset-F1 | Onset-MAE | Key-MAE | Effective-MAE | Key mediaan | Key max | Vroeg/laat key | Vroeg/laat effective | Gewijzigd |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| clean:long | A | 3 | 3/2/0 | 0.750 | 0.750 | 8.416 | 1336.667 | 1336.667 | 1490.000 | 2010.000 | 1/2 | 1/2 | 0 |
| clean:long | B | 3 | 3/2/0 | 0.750 | 0.750 | 8.416 | 721.780 | 721.780 | 510.000 | 1490.000 | 1/2 | 1/2 | 1 |
| clean:long | C | 3 | 3/2/0 | 0.750 | 0.750 | 8.416 | 721.780 | 721.780 | 510.000 | 1490.000 | 1/2 | 1/2 | 1 |
| clean:overlap | A | 4 | 4/0/0 | 1.000 | 1.000 | 5.929 | 4007.453 | 4007.453 | 4204.906 | 4810.000 | 0/4 | 0/4 | 0 |
| clean:overlap | B | 4 | 4/0/0 | 1.000 | 1.000 | 5.929 | 1909.137 | 1909.137 | 1810.109 | 4009.812 | 0/3 | 0/3 | 3 |
| clean:overlap | C | 4 | 4/0/0 | 1.000 | 1.000 | 5.929 | 1235.964 | 1235.964 | 1337.967 | 2261.404 | 0/3 | 0/3 | 4 |
| clean:repeated | A | 5 | 5/0/0 | 1.000 | 1.000 | 2.416 | 631.951 | 631.951 | 1.762 | 3151.625 | 0/1 | 0/1 | 0 |
| clean:repeated | B | 5 | 5/0/0 | 1.000 | 1.000 | 2.416 | 2.091 | 2.091 | 1.762 | 3.669 | 0/0 | 0/0 | 1 |
| clean:repeated | C | 5 | 5/0/0 | 1.000 | 1.000 | 2.416 | 2.091 | 2.091 | 1.762 | 3.669 | 0/0 | 0/0 | 1 |
| clean:sustain | A | 5 | 5/0/0 | 1.000 | 1.000 | 5.332 | 4316.488 | 1646.488 | 5010.000 | 5510.000 | 0/5 | 0/4 | 0 |
| clean:sustain | B | 5 | 5/0/0 | 1.000 | 1.000 | 5.332 | 3251.522 | 583.581 | 3194.855 | 5510.000 | 0/5 | 0/3 | 3 |
| clean:sustain | C | 5 | 5/0/0 | 1.000 | 1.000 | 5.332 | 3203.822 | 535.880 | 3194.855 | 5271.497 | 0/5 | 0/3 | 4 |
| clean:TOTAL | A | 17 | 17/2/0 | 0.944 | 0.944 | 5.159 | 2634.235 | 1848.941 | 2810.000 | 5510.000 | 1/12 | 1/11 | 0 |
| clean:TOTAL | B | 17 | 17/2/0 | 0.944 | 0.944 | 5.159 | 1533.527 | 748.838 | 1000.000 | 5510.000 | 1/10 | 1/8 | 8 |
| clean:TOTAL | C | 17 | 17/2/0 | 0.944 | 0.944 | 5.159 | 1361.104 | 576.415 | 1000.000 | 5271.497 | 1/10 | 1/8 | 10 |
| noise:overlap | A | 4 | 4/0/0 | 1.000 | 1.000 | 3.222 | 3397.453 | 3397.453 | 3404.906 | 4400.000 | 0/4 | 0/4 | 0 |
| noise:overlap | B | 4 | 4/0/0 | 1.000 | 1.000 | 3.222 | 3391.806 | 3391.806 | 3393.612 | 4400.000 | 0/4 | 0/4 | 1 |
| noise:overlap | C | 4 | 4/0/0 | 1.000 | 1.000 | 3.222 | 3391.806 | 3391.806 | 3393.612 | 4400.000 | 0/4 | 0/4 | 1 |
| noise:sustain | A | 1 | 1/0/0 | 1.000 | 1.000 | 5.816 | 5010.000 | 1810.000 | 5010.000 | 5010.000 | 0/1 | 0/1 | 0 |
| noise:sustain | B | 1 | 1/0/0 | 1.000 | 1.000 | 5.816 | 5010.000 | 1810.000 | 5010.000 | 5010.000 | 0/1 | 0/1 | 0 |
| noise:sustain | C | 1 | 1/0/0 | 1.000 | 1.000 | 5.816 | 5010.000 | 1810.000 | 5010.000 | 5010.000 | 0/1 | 0/1 | 0 |
| noise:TOTAL | A | 5 | 5/0/0 | 1.000 | 1.000 | 3.741 | 3719.963 | 3079.963 | 4009.812 | 5010.000 | 0/5 | 0/5 | 0 |
| noise:TOTAL | B | 5 | 5/0/0 | 1.000 | 1.000 | 3.741 | 3715.445 | 3075.445 | 3987.223 | 5010.000 | 0/5 | 0/5 | 1 |
| noise:TOTAL | C | 5 | 5/0/0 | 1.000 | 1.000 | 3.741 | 3715.445 | 3075.445 | 3987.223 | 5010.000 | 0/5 | 0/5 | 1 |
| all:TOTAL | A | 22 | 22/2/0 | 0.957 | 0.957 | 4.837 | 2880.992 | 2128.719 | 2980.812 | 5510.000 | 1/17 | 1/16 | 0 |
| all:TOTAL | B | 22 | 22/2/0 | 0.957 | 0.957 | 4.837 | 2029.417 | 1277.612 | 1875.702 | 5510.000 | 1/15 | 1/13 | 9 |
| all:TOTAL | C | 22 | 22/2/0 | 0.957 | 0.957 | 4.837 | 1896.181 | 1144.376 | 1424.407 | 5271.497 | 1/15 | 1/13 | 11 |

### Per case

| Case | Policy | GT | TP/FP/FN | Onset-MAE ms | Key-MAE ms | Effective-MAE ms | Mediaan ms | Max ms | Gewijzigd |
|---|---|---|---|---|---|---|---|---|---|
| hold_c4_4s | A | 1 | 1/1/0 | 10.195 | 2010.000 | 2010.000 | 2010.000 | 2010.000 | 0 |
| hold_c4_4s | B | 1 | 1/1/0 | 10.195 | 165.341 | 165.341 | 165.341 | 165.341 | 1 |
| hold_c4_4s | C | 1 | 1/1/0 | 10.195 | 165.341 | 165.341 | 165.341 | 165.341 | 1 |
| hold_a4_55s | A | 1 | 1/0/0 | 5.169 | 510.000 | 510.000 | 510.000 | 510.000 | 0 |
| hold_a4_55s | B | 1 | 1/0/0 | 5.169 | 510.000 | 510.000 | 510.000 | 510.000 | 0 |
| hold_a4_55s | C | 1 | 1/0/0 | 5.169 | 510.000 | 510.000 | 510.000 | 510.000 | 0 |
| hold_e4_75s | A | 1 | 1/1/0 | 9.884 | 1490.000 | 1490.000 | 1490.000 | 1490.000 | 0 |
| hold_e4_75s | B | 1 | 1/1/0 | 9.884 | 1490.000 | 1490.000 | 1490.000 | 1490.000 | 0 |
| hold_e4_75s | C | 1 | 1/1/0 | 9.884 | 1490.000 | 1490.000 | 1490.000 | 1490.000 | 0 |
| pedal_g4 | A | 1 | 1/0/0 | 5.588 | 5010.000 | 1810.000 | 5010.000 | 5010.000 | 0 |
| pedal_g4 | B | 1 | 1/0/0 | 5.588 | 3194.855 | 5.145 | 3194.855 | 3194.855 | 1 |
| pedal_g4 | C | 1 | 1/0/0 | 5.588 | 3194.855 | 5.145 | 3194.855 | 3194.855 | 1 |
| pedal_pair | A | 2 | 2/0/0 | 5.196 | 5380.000 | 1605.000 | 5380.000 | 5510.000 | 0 |
| pedal_pair | B | 2 | 2/0/0 | 5.196 | 4752.841 | 977.841 | 4752.841 | 5510.000 | 1 |
| pedal_pair | C | 2 | 2/0/0 | 5.196 | 4633.589 | 858.589 | 4633.589 | 5271.497 | 2 |
| pedal_reattack | A | 2 | 2/0/0 | 5.341 | 2906.219 | 1606.219 | 2906.219 | 4812.438 | 0 |
| pedal_reattack | B | 2 | 2/0/0 | 5.341 | 1778.538 | 478.538 | 1778.538 | 2557.077 | 1 |
| pedal_reattack | C | 2 | 2/0/0 | 5.341 | 1778.538 | 478.538 | 1778.538 | 2557.077 | 1 |
| repeated_d4 | A | 5 | 5/0/0 | 2.416 | 631.951 | 631.951 | 1.762 | 3151.625 | 0 |
| repeated_d4 | B | 5 | 5/0/0 | 2.416 | 2.091 | 2.091 | 1.762 | 3.669 | 1 |
| repeated_d4 | C | 5 | 5/0/0 | 2.416 | 2.091 | 2.091 | 1.762 | 3.669 | 1 |
| staggered_chord | A | 4 | 4/0/0 | 5.929 | 4007.453 | 4007.453 | 4204.906 | 4810.000 | 0 |
| staggered_chord | B | 4 | 4/0/0 | 5.929 | 1909.137 | 1909.137 | 1810.109 | 4009.812 | 3 |
| staggered_chord | C | 4 | 4/0/0 | 5.929 | 1235.964 | 1235.964 | 1337.967 | 2261.404 | 4 |
| pedal_g4_noise | A | 1 | 1/0/0 | 5.816 | 5010.000 | 1810.000 | 5010.000 | 5010.000 | 0 |
| pedal_g4_noise | B | 1 | 1/0/0 | 5.816 | 5010.000 | 1810.000 | 5010.000 | 5010.000 | 0 |
| pedal_g4_noise | C | 1 | 1/0/0 | 5.816 | 5010.000 | 1810.000 | 5010.000 | 5010.000 | 0 |
| staggered_chord_noise | A | 4 | 4/0/0 | 3.222 | 3397.453 | 3397.453 | 3404.906 | 4400.000 | 0 |
| staggered_chord_noise | B | 4 | 4/0/0 | 3.222 | 3391.806 | 3391.806 | 3393.612 | 4400.000 | 1 |
| staggered_chord_noise | C | 4 | 4/0/0 | 3.222 | 3391.806 | 3391.806 | 3393.612 | 4400.000 | 1 |

## Lange noten: iedere gematchte noot

GT onset/key/pedal, raw peaks en endpoints in seconden. Iedere vroege offset is zichtbaar, ook wanneer A al vroeg eindigde. Een extra modelprediction heeft geen GT en staat afzonderlijk bij modelproblemen.

| Case/pitch | GT onset | GT key | GT pedal | Raw offsetpeaks (s:score) | Upstream | A | B/state | C/state | Decoder |
|---|---|---|---|---|---|---|---|---|---|
| hold_c4_4s/60 | 0.400 | 4.400 | 4.400 | 4.565:0.495, 5.250:0.870 | 6.410 | 6.410 | 4.565/late | 4.565/late | six_second_cap |
| hold_a4_55s/69 | 0.600 | 6.100 | 6.100 | 6.839:0.837 (buiten B-venster) | 6.610 | 6.610 | 6.610/late | 6.610/late | six_second_cap |
| hold_e4_75s/64 | 0.500 | 8.000 | 8.000 | 8.642:0.672 (buiten B-venster) | 6.510 | 6.510 | 6.510/early | 6.510/early | six_second_cap |

**VROEGE LANGE NOOT:** hold_e4_75s pitch 64: key 8.000, A 6.510, B 6.510, C 6.510. Ongewijzigd vroeg A-probleem; geen nieuwe kandidaatregressie.

**Belangrijke dekkingsbeperking:** 0 van deze 3 lange noten had onder A al een correcte offset binnen 50 ms. De specifieke regressievraag 'A-correcte lange noot door B vroeg afgebroken' is hierdoor niet overtuigend getest met echte modeloutputs. De helpers testen die failure wel deterministisch. Geen ontbrekend gevaarlijk geval achteraf toegevoegd of policy getuned.

## Sustain: key release en pedal-release afzonderlijk

| Case/pitch | Policy | GT key / pedal | End | Signed key-fout ms | Signed pedal-fout ms | Pedal-state |
|---|---|---|---|---|---|---|
| pedal_g4/67@0.400 | A | 1.400/4.600 | 6.410 | 5010.000 | 1810.000 | late |
| pedal_g4/67@0.400 | B | 1.400/4.600 | 4.595 | 3194.855 | -5.145 | correct |
| pedal_g4/67@0.400 | C | 1.400/4.600 | 4.595 | 3194.855 | -5.145 | correct |
| pedal_pair/60@0.500 | A | 1.000/5.400 | 6.510 | 5510.000 | 1110.000 | late |
| pedal_pair/60@0.500 | B | 1.000/5.400 | 6.510 | 5510.000 | 1110.000 | late |
| pedal_pair/60@0.500 | C | 1.000/5.400 | 6.271 | 5271.497 | 871.497 | late |
| pedal_pair/64@1.500 | A | 2.250/5.400 | 7.500 | 5250.000 | 2100.000 | late |
| pedal_pair/64@1.500 | B | 2.250/5.400 | 6.246 | 3995.681 | 845.681 | late |
| pedal_pair/64@1.500 | C | 2.250/5.400 | 6.246 | 3995.681 | 845.681 | late |
| pedal_reattack/67@0.400 | A | 0.800/1.800 | 1.800 | 1000.000 | -0.000 | correct |
| pedal_reattack/67@0.400 | B | 0.800/1.800 | 1.800 | 1000.000 | -0.000 | correct |
| pedal_reattack/67@0.400 | C | 0.800/1.800 | 1.800 | 1000.000 | -0.000 | correct |
| pedal_reattack/67@1.800 | A | 2.200/3.800 | 7.012 | 4812.438 | 3212.437 | late |
| pedal_reattack/67@1.800 | B | 2.200/3.800 | 4.757 | 2557.077 | 957.077 | late |
| pedal_reattack/67@1.800 | C | 2.200/3.800 | 4.757 | 2557.077 | 957.077 | late |
| pedal_g4_noise/67@0.400 | A | 1.400/4.600 | 6.410 | 5010.000 | 1810.000 | late |
| pedal_g4_noise/67@0.400 | B | 1.400/4.600 | 6.410 | 5010.000 | 1810.000 | late |
| pedal_g4_noise/67@0.400 | C | 1.400/4.600 | 6.410 | 5010.000 | 1810.000 | late |

### Onafhankelijke synthese-extinctie en voorspeld pedaal

- pedal_g4: MIDI pedaal [[0.3, 127], [4.6, 0]]; voorspeld pedaal `[]`; globale signaalextinctie 5.443628 s. Isolated stems: `[]`.
- pedal_pair: MIDI pedaal [[0.3, 127], [5.4, 0]]; voorspeld pedaal `[]`; globale signaalextinctie 6.271497 s. Isolated stems: `[{'pitch': 60, 'onset': 0.5, 'end': 6.212789115646259, 'audio': 'backend/data/ground_truth/rendered/independent_validation/pedal_pair-stem-0.wav', 'audioSha256': 'ee682d1ad39d5324cd09f4b84fd318d62668605f6701acb25d3c88ff7b108d83', 'midi': 'backend/data/ground_truth/fixtures/independent_validation/pedal_pair-stem-0.mid', 'midiSha256': '5061d2fdef82d8669ffca9d999d56b6418ad45b882029eacae734ebee4a89650'}, {'pitch': 64, 'onset': 1.5, 'end': 6.271496598639456, 'audio': 'backend/data/ground_truth/rendered/independent_validation/pedal_pair-stem-1.wav', 'audioSha256': 'dd53c1be370df5097bdd965b4cb7f56162c15f375837284456743188e010f06e', 'midi': 'backend/data/ground_truth/fixtures/independent_validation/pedal_pair-stem-1.mid', 'midiSha256': '79bcef4e3ff39ffb3156e7edc6925255da98aa8e531ae049429e2874522cd222'}]`.
- pedal_reattack: MIDI pedaal [[0.3, 127], [3.8, 0]]; voorspeld pedaal `[]`; globale signaalextinctie 4.781973 s. Isolated stems: `[]`.

## Alle regressies

Ieder verslechterd gematcht event tegenover A staat hieronder, ook als het gemiddelde verbetert. Signed fouten en volledige raw peaklijsten staan in notes-CSV/JSON. Key-verbetering alleen is bij sustain geen succes als effective/pedal-release slechter wordt.

Geen geobserveerde verslechterde gematchte noot tegenover A in deze set. Dat bewijst geen algemene sustainveiligheid.

### Bestaande model/decoderproblemen, geen nieuwe B/C-wijziging

| Case | Extra/onset-mismatch prediction | Onset | A/B/C |
|---|---|---|---|
| hold_c4_4s | 66 | 1.939 | 1.950/1.950/1.950 |
| hold_e4_75s | 76 | 0.512 | 6.510/6.510/6.510 |

Niet gematchte referentienoten: `[]`.
Herhaalde noten behouden exact hun pitch/onset/eventcount. Veranderingen mogen niets verlengen voorbij A; de policyvoorkeur zoekt strikt vóór de volgende same-pitch onset. Overlap/chordpitches worden niet als één event behandeld.

## Clean versus vaste achtergrondruis

Exact: PCG64, stereo Gaussian, lfilter [1]/[1,-0.97], RMS -70 dBFS/channel, seeds 20261007 en 20261008; additief zonder signaalnormalisatie, saved PCM24. Het is een lage gekleurde ruisproxy, geen volledige microfoon/ruimte-simulatie. MIDI/duur zijn ongewijzigd. Verschillen A/B tussen varianten kunnen ook door modelrespons op ruis komen; C-minus-B isoleert de guardbijdrage binnen dezelfde inferentie.

- pedal_g4: native terminal-silence bound 5.443628117913832; C≠B events 0; key-MAE A/B/C 5010.000/3194.855/3194.855 ms; effective-MAE A/B/C 1810.000/5.145/5.145 ms.
- pedal_g4_noise: native terminal-silence bound None; C≠B events 0; key-MAE A/B/C 5010.000/5010.000/5010.000 ms; effective-MAE A/B/C 1810.000/1810.000/1810.000 ms.
- staggered_chord: native terminal-silence bound 4.517120181405896; C≠B events 1; key-MAE A/B/C 4007.453/1909.137/1235.964 ms; effective-MAE A/B/C 4007.453/1909.137/1235.964 ms.
- staggered_chord_noise: native terminal-silence bound None; C≠B events 0; key-MAE A/B/C 3397.453/3391.806/3391.806 ms; effective-MAE A/B/C 3397.453/3391.806/3391.806 ms.

Op beide noisy WAVs ontbreekt exacte digitale eindstilte. Daarom kan de bevroren guard geen extra C-verbetering boven B leveren; **C=B** op de noisy cases. Dit zegt niets over de juistheid van hun gemeenschappelijke offsets. Geen epsilon/ruisdrempel toegevoegd.

C-specifieke effectieve-release-MAE-winst (B minus C), clean/noise: `[{'clean': 'pedal_g4', 'noise': 'pedal_g4_noise', 'cleanGuardChangedNotes': 0, 'cleanGuardKeyMaeGainMs': 0.0, 'cleanGuardEffectiveMaeGainMs': 0.0, 'noiseGuardChangedNotes': 0, 'noiseGuardKeyMaeGainMs': 0.0, 'noiseGuardEffectiveMaeGainMs': 0.0, 'guardGainLostWithNoise': False}, {'clean': 'staggered_chord', 'noise': 'staggered_chord_noise', 'cleanGuardChangedNotes': 1, 'cleanGuardKeyMaeGainMs': 673.1730796485258, 'cleanGuardEffectiveMaeGainMs': 673.1730796485258, 'noiseGuardChangedNotes': 0, 'noiseGuardKeyMaeGainMs': 0.0, 'noiseGuardEffectiveMaeGainMs': 0.0, 'guardGainLostWithNoise': True}]`. **FAIL guard-betrouwbaarheid:** waargenomen cleanwinst verdwijnt met ruis.

### Ieder matched clean/noise-event

Dit zijn veranderingen tussen twee inferenties (clean en ruis), afzonderlijk van policyregressies tegenover A binnen één inferentie. Key/pedal-referenties blijven identiek; signed effectieve fouten zijn ms.

| Noise-case/pitch | Policy | Key / effective release | Clean end | Noise end | Clean fout ms | Noise fout ms | Slechter met ruis |
|---|---|---|---|---|---|---|---|
| pedal_g4_noise/67 | B | 1.400/4.600 | 4.595 | 6.410 | -5.145 | 1810.000 | True |
| pedal_g4_noise/67 | C | 1.400/4.600 | 4.595 | 6.410 | -5.145 | 1810.000 | True |
| staggered_chord_noise/48 | B | 3.600/3.600 | 3.593 | 6.400 | -6.518 | 2800.000 | True |
| staggered_chord_noise/48 | C | 3.600/3.600 | 3.593 | 6.400 | -6.518 | 2800.000 | True |
| staggered_chord_noise/60 | B | 1.600/1.600 | 3.861 | 3.980 | 2261.404 | 2380.000 | True |
| staggered_chord_noise/60 | C | 1.600/1.600 | 3.861 | 3.980 | 2261.404 | 2380.000 | True |
| staggered_chord_noise/64 | B | 2.500/2.500 | 3.859 | 6.900 | 1358.814 | 4400.000 | True |
| staggered_chord_noise/64 | C | 2.500/2.500 | 3.859 | 6.900 | 1358.814 | 4400.000 | True |
| staggered_chord_noise/67 | B | 3.200/3.200 | 7.210 | 7.187 | 4009.812 | 3987.223 | False |
| staggered_chord_noise/67 | C | 3.200/3.200 | 4.517 | 7.187 | 1317.120 | 3987.223 | True |

## Bestaande piano-audio: alleen diagnostiek

### 140_Cm_Piano_VKeys_02_268_2

SHA256 `66ff0c8706d151f8980a633a3563a8671131f1b05e9199bec650495fba9686d7`; 3.432 s; 15 predictions; pitches [55, 59, 60, 62, 64, 67, 72, 74, 79, 84].
B wijzigt 7 offsets; C wijzigt 7. Terminal-silence bound None; boundary-events 5.
Geen onafhankelijke key/pedal/audible labels; geen accuracy, muzikale verbetering of correctheid geconcludeerd uit minder/langer/korter gedetecteerde noten. Beide zijn bestaande sampleloops, geen bevestigde nieuwe microfoonperformance. De 140_Cm-clip is eerder technisch getest en vormt hier alleen nieuwe policytrace, geen nieuw onafhankelijk kwaliteitsbewijs.

### 120_G_Offbeat_01_53_SP

SHA256 `92c8e189edd1f194047b0af44c6b7101da63cdc7d69960843dad6e08712cef3c`; 16.000 s; 172 predictions; pitches [43, 45, 48, 50, 55, 57, 59, 60, 62, 64, 66, 67, 69, 74].
B wijzigt 113 offsets; C wijzigt 113. Terminal-silence bound None; boundary-events 4.
Geen onafhankelijke key/pedal/audible labels; geen accuracy, muzikale verbetering of correctheid geconcludeerd uit minder/langer/korter gedetecteerde noten. Beide zijn bestaande sampleloops, geen bevestigde nieuwe microfoonperformance. De 140_Cm-clip is eerder technisch getest en vormt hier alleen nieuwe policytrace, geen nieuw onafhankelijk kwaliteitsbewijs.

## Beslissing: zes gevraagde antwoorden

1. **Is B veilig genoeg op onafhankelijk materiaal?** Niet bewezen: geen geobserveerde safety-fail in deze set, maar acht syntheseplannen met één SoundFont en geen bevestigde echte akoestische labels volstaan niet voor READY.
2. **Is C duidelijk beter dan B buiten de originele benchmark?** Vergelijk de clean/noise-totalen hierboven. Eventuele cleanwinst door de guard is afzonderlijk zichtbaar; bij beide noisevarianten is C exact B. Er is geen aangetoonde algemene voorsprong op niet-perfect-stille opnames.
3. **Is de runaway/stiltecomponent bruikbaar op niet-perfect-stille audio?** Nee in deze vaste ruisproef: er is geen exact-zero bound en de guard abstineert. Herkenning van cap/sequence-end blijft bruikbaar als diagnose, maar geeft geen betrouwbare muzikale release.
4. **Zijn er te vroeg afgebroken lange/sustainnoten?** Alle early-states staan in de long/sustaintabellen; safety-fails onderscheiden nieuw beleidsschade van reeds vroege A. De 7.5 s held note wordt upstream door de bestaande 600-framegrens vroeg gesloten; deze stap lost dat niet op.
5. **Welke policy als eerste productiefix?** Geen nu. B blijft het kleinere onderzoeks-kandidaatonderdeel; C biedt geen aantoonbare extra werking zonder perfecte eindstilte.
6. **Is het bewijs sterk genoeg om dat nu te doen?** Nee. B: **MORE VALIDATION NEEDED**; C: **DO NOT SHIP**. Geen automatische productiewijziging. Voor READY ontbreken onafhankelijke akoestische key/pedal-events en bredere timbre/noise-validatie. C verliest bovendien de guardwinst bij achtergrondruis.

## Reproduceren en bestanden

Zie `../experiments/independent_validation/README.md`. Eerste run: prepare, daarna run --capture. Volgende run: run zonder --capture gebruikt dezelfde opgeslagen raw heads, geen inferentie. Alle input/outputhashes worden gecontroleerd; geen labels worden uit predictions gegenereerd.
Nieuwe code: onafhankelijke prepare/capture/assessment/report en tests. Nieuwe fixtures: acht MIDI's, twee onafhankelijke pair-stem-MIDI's en manifest. Nieuwe rapporten: dit Markdown, metrics-CSV, notes-CSV en JSON. WAVs/modeloutputs zijn gitignored; bestaande worktree volledig behouden.

## Verificatie van deze opdracht

62 tests geslaagd: 19 bestaande offset-policytests, 15 benchmarktests, 12 ByteDance-adaptertests en 16 nieuwe validatietests. Drie bestaande FastAPI/Starlette-deprecationwarnings. Geen failures in deze suites; bestaande testverwachtingen niet aangepast. De bekende Windows oversized-uploadfailure is buiten deze validatie gehouden: niet opnieuw gedraaid of gerepareerd. Frontend is ongewijzigd en niet opnieuw getest.
Een clean hold_c4_4s WAV is opnieuw gerenderd met het vastgelegde commando: byte-identieke SHA256. De offline replay gebruikt bevroren heads; nootbeslissingen, metrics en CSV's worden op identieke resultaten gecontroleerd. Alle 155 reeds aanwezige bron/fixture/baseline/policy/upstreambestanden uit de startsnapshot blijven identiek. Geen staging, commit of push.
