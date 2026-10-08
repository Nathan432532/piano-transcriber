# MAPS ENSTDkCl: onafhankelijke akoestische validatie

Run 7 oktober 2026. **BYTEDANCE READY WITH KNOWN OFFSET LIMITATION**; **B DO NOT SHIP**.

ByteDance blijft de primaire engine voor een demo met menselijke correctie van korte passages. Deze test rechtvaardigt geen claim van foutloze MIDI of betrouwbare lange nootduren. Policy B beschadigt correcte releases en blijft uitsluitend offline. Geen productiecode, thresholds, decoder, schema of editor gewijzigd.

## Data, integriteit en labels

Officiële [Zenodo-release 0.4](https://zenodo.org/records/18160555), uitsluitend ENSTDkCl.zip. Grootte **2608287080 bytes**, gecontroleerde MD5 **72bbdf40eb7af69225755e165a0a0a08**. ZIP en uitgepakte data staan buiten de repo, onder `<MAPS-root>`. Het uitgepakte payload is **4325567515 bytes**; samen met ZIP **6933854595 bytes (6,46 GiB)**, exclusief inferentiecache en kleine metadata. ZIP bevat 12239 entries; 3999 WAV/MIDI/TXT-paren: ISOL 999, RAND 1200, UCHO 1770, MUS 30.

MAPS gebruikt fysieke Disklavier-piano's, aangestuurd door MIDI; dit is akoestische audio met onafhankelijke bronlabels, geen menselijke liveperformance. ENSTDkCl is de close-microphone-conditie. Zie de [oorspronkelijke auteurs](https://adasp.telecom-paris.fr/resources/2010-07-08-maps-database/). ByteDance vermeldt [MAESTRO-training](https://github.com/bytedance/piano_transcription/blob/master/README.md); MAESTRO is niet gebruikt als validatiedata.

Alle geïnspecteerde audio: 44100 Hz, stereo PCM16. Naamstammen met `_ENSTDkCl` koppelen WAV, type-0 MIDI en TXT. MIDI note-on/off, velocity, tempo en CC64 worden rechtstreeks gelezen uit officiële MID-bestanden. Ground truth komt nooit uit predictions of appcorrecties. CC64 down/up is daadwerkelijk gecontroleerd, niet afgeleid uit alleen S0/S1 in de naam.

Raw MIDI-tijdlijn: globale shift **0 s**, geen voorspellinggestuurde alignment. Mechanische toets-/hamerrespons en akoestische uitsterving kunnen afwijken van MIDI-commando's; onsetmatching is daarom geen bewijs van sample-exacte audio/MIDI-alignment. De hier gemeten secondegrote duurfouten kunnen niet worden verklaard door een kleine constante onsetlatentie.

Per-pitch ASCII/MIDI-audit: 3999 paren, maximale onsetafwijking 0.500 ms. Op de daadwerkelijk gescoorde subset maximaal 0.050 ms verschil tussen TXT en CC64-effectieve release, **geen verschil boven 1 ms**.

Buiten de geselecteerde vensters zijn 13 afwijkende effectieve TXT-releases gevonden, maximaal 1,633 s. Concreet: bk_xmas1, pitch 37, onset 316,052 s; note-off en CC64-down staan beide op 316,206 s, maar note-off staat eerst in MIDI. TXT loopt door tot 317,839 s. De bestaande MIDI-parser respecteert eventvolgorde. Deze afwijking ligt buiten het [0,10)s-scorevenster; labels en matcher zijn niet aangepast. Volledige uitzonderingen staan in review.json.

Bij de eerste modelvrije audit gaf sortering op afgeronde gelijktijdige ASCII-onsets tien onterechte pitch-orderflags in MUS. Daarom is de oorspronkelijke selectie gekozen uit 20 toen geaccepteerde MUS-bestanden. De nieuwe helper groepeert per pitch; alle 3999 paren hebben overeenkomende aantallen/pitches. De **al bevroren 24 cases blijven ongewijzigd**; de historische flags zijn transparant bewaard in het manifest. De selectie is dus de eerste vijf lexicografische MUS-bestanden van die oorspronkelijke geaccepteerde inventaris, niet van de later gecorrigeerde volledige inventaris.

## Bevroren subset

Manifest bevroren vóór inferentie op 2026-10-07T18:32:35.222882+00:00; SHA256 `eb6560e2f7306400a6f561bb6f615709fb20cb722fea801cc3a29ff968b021c1`. Vier normale noten, vijf lange noten, drie repeated, drie sustain, vier akkoorden, vijf muziekfragmenten. Selectie alleen op MIDI/metadata: dichtst bij vooraf gekozen pitch-/duurdoelen, velocity 80 als tweede criterium, lexicografische ties. Geen selectie op modelkwaliteit.

Muziek: oorspronkelijke samples [0,15)s als invoer voor beide modellen; score onsets [0,10)s. Overige cases: volledige audio. Ends worden niet afgeknipt tot het scorevenster. Geen geselecteerde GT-release valt voorbij het audiovenster (0 censored notes). Onderstaande stammen hebben steeds officiële .wav/.mid/.txt-partners; exacte relatieve paden en SHA256 staan in het manifest.

| Case | Type | Originele stem | GT | Pitchrange | CC64 down | Audio / onset-score (s) |
|---|---|---|---|---|---|---|
| 01_isolated | isolated | MAPS_ISOL_NO_P_S0_M36_ENSTDkCl | 1 | [36, 36] | False | [0.0, 4.120997732426304] / [0.0, 4.120997732426304] |
| 02_isolated | isolated | MAPS_ISOL_NO_F_S0_M60_ENSTDkCl | 1 | [60, 60] | False | [0.0, 4.126984126984127] / [0.0, 4.126984126984127] |
| 03_isolated | isolated | MAPS_ISOL_NO_F_S0_M84_ENSTDkCl | 1 | [84, 84] | False | [0.0, 4.139002267573696] / [0.0, 4.139002267573696] |
| 04_isolated | isolated | MAPS_ISOL_NO_M_S0_M100_ENSTDkCl | 1 | [100, 100] | False | [0.0, 4.120997732426304] / [0.0, 4.120997732426304] |
| 05_long | long | MAPS_ISOL_LG_F_S0_M105_ENSTDkCl | 1 | [105, 105] | False | [0.0, 5.702993197278912] / [0.0, 5.702993197278912] |
| 06_long | long | MAPS_ISOL_LG_F_S0_M95_ENSTDkCl | 1 | [95, 95] | False | [0.0, 7.661995464852608] / [0.0, 7.661995464852608] |
| 07_long | long | MAPS_ISOL_LG_M_S0_M82_ENSTDkCl | 1 | [82, 82] | False | [0.0, 10.197981859410431] / [0.0, 10.197981859410431] |
| 08_long | long | MAPS_ISOL_LG_F_S0_M62_ENSTDkCl | 1 | [62, 62] | False | [0.0, 14.109002267573697] / [0.0, 14.109002267573697] |
| 09_long | long | MAPS_ISOL_LG_F_S0_M31_ENSTDkCl | 1 | [31, 31] | False | [0.0, 20.16498866213152] / [0.0, 20.16498866213152] |
| 10_repeated | repeated | MAPS_ISOL_RE_F_S0_M49_ENSTDkCl | 15 | [49, 49] | False | [0.0, 6.203990929705215] / [0.0, 6.203990929705215] |
| 11_repeated | repeated | MAPS_ISOL_RE_M_S0_M66_ENSTDkCl | 15 | [66, 66] | False | [0.0, 6.203990929705215] / [0.0, 6.203990929705215] |
| 12_repeated | repeated | MAPS_ISOL_RE_M_S0_M89_ENSTDkCl | 15 | [89, 89] | False | [0.0, 6.202993197278912] / [0.0, 6.202993197278912] |
| 13_sustain | sustain | MAPS_ISOL_NO_P_S1_M48_ENSTDkCl | 1 | [48, 48] | True | [0.0, 4.57] / [0.0, 4.57] |
| 14_sustain | sustain | MAPS_ISOL_NO_M_S1_M67_ENSTDkCl | 1 | [67, 67] | True | [0.0, 4.573990929705215] / [0.0, 4.573990929705215] |
| 15_sustain | sustain | MAPS_ISOL_NO_M_S1_M90_ENSTDkCl | 1 | [90, 90] | True | [0.0, 4.57] / [0.0, 4.57] |
| 16_chords | chords | MAPS_UCHO_C0-24_I60-68_S0_n1_ENSTDkCl | 2 | [43, 67] | False | [0.0, 3.1229931972789116] / [0.0, 3.1229931972789116] |
| 17_chords | chords | MAPS_UCHO_C0-5-9_I32-96_S0_n3_ENSTDkCl | 3 | [62, 71] | False | [0.0, 3.1219954648526076] / [0.0, 3.1219954648526076] |
| 18_chords | chords | MAPS_RAND_P2_M36-95_I60-68_S0_n1_ENSTDkCl | 2 | [38, 72] | False | [0.0, 2.7660090702947846] / [0.0, 2.7660090702947846] |
| 19_chords | chords | MAPS_RAND_P3_M21-108_I32-96_S0_n17_ENSTDkCl | 3 | [61, 83] | False | [0.0, 2.7549886621315194] / [0.0, 2.7549886621315194] |
| 20_music | music | MAPS_MUS-bk_xmas1_ENSTDkCl | 71 | [25, 102] | True | [0.0, 15.0] / [0.0, 10.0] |
| 21_music | music | MAPS_MUS-bk_xmas4_ENSTDkCl | 83 | [31, 96] | True | [0.0, 15.0] / [0.0, 10.0] |
| 22_music | music | MAPS_MUS-bor_ps6_ENSTDkCl | 76 | [37, 82] | True | [0.0, 15.0] / [0.0, 10.0] |
| 23_music | music | MAPS_MUS-chpn-e01_ENSTDkCl | 119 | [24, 101] | True | [0.0, 15.0] / [0.0, 10.0] |
| 24_music | music | MAPS_MUS-chpn-p19_ENSTDkCl | 169 | [31, 99] | True | [0.0, 15.0] / [0.0, 10.0] |

## Matching en vergelijking

Bestaande `benchmarks.metrics.score/read_midi/aggregate`, mir_eval 0.8.2: één-op-één matching, gelijke integer MIDI-pitch (1 cent tolerantie), onset ≤50 ms, offset uitgesloten van primaire matching. Micro-aggregatie over alle noten. MAE/mediaan/max alleen op gematchte noten; gemiste noten blijven FN, extra noten FP. De onsetmaximumfout wordt begrensd door de matcher en zegt niets over de fouten van FN/FP.

| Metric | ByteDance A | Basic Pitch |
|---|---|---|
| GT | 585 | 585 |
| Predicted | 680 | 462 |
| TP | 541 | 342 |
| FP | 139 | 120 |
| FN | 44 | 243 |
| Precision | 0.796 | 0.740 |
| Recall | 0.925 | 0.585 |
| F1 | 0.855 | 0.653 |
| Onset MAE ms | 13.083 | 14.185 |
| Onset mediaan ms | 9.275 | 10.951 |
| Onset max ms | 49.265 | 48.751 |
| Key offset MAE ms | 301.831 | 219.816 |
| Key offset mediaan ms | 117.111 | 122.852 |
| Key offset max ms | 12052.990 | 6946.367 |
| CC64 effective MAE ms | 148.474 | 273.700 |
| CC64 effective mediaan ms | 50.980 | 123.004 |
| CC64 effective max ms | 12052.990 | 6946.367 |
| Key error >250 ms | 161 | 70 |
| Key error >500 ms | 97 | 22 |
| Key error >1 s | 36 | 8 |
| Key early >50 ms | 75 | 58 |
| Key late >50 ms | 270 | 196 |
| End exact audio duration | 5 | 0 |
| End within 10 ms audio duration | 5 | 0 |

ByteDance heeft overall meer FP (139 tegenover 120), ondanks veel hogere recall. De hypothese ‘Basic Pitch altijd meer extra noten’ klopt dus niet. Basic Pitch geeft meer FP bij losse/lange/sustainnoten en akkoorden; ByteDance bij repeated en muziek. Repeated F1 is hier hoger voor Basic Pitch. ByteDance is sterker in de overige categorieën, maar de long-score laat de gemiste pitch 105 expliciet meetellen.

De offsetgemiddelden hierboven hebben verschillende coverage (541 versus 342 matches). Ter controle volgt vergelijking op dezelfde onafhankelijke GT-identiteiten die **beide** modellen matchten; geen nieuwe matching of selectie op offsetkwaliteit.

| Engine | Gedeelde GT matches | Onset MAE ms | Key MAE ms | Effective MAE ms |
|---|---|---|---|---|
| bytedance | 337 | 13.227 | 274.238 | 160.560 |
| basic_pitch | 337 | 13.885 | 222.130 | 276.961 |

## Per categorie

| Categorie | Engine | GT | Pred | TP/FP/FN | P/R/F1 | Onset MAE/mediaan/max ms | Key MAE/mediaan/max ms | Effective MAE ms |
|---|---|---|---|---|---|---|---|---|
| chords | bytedance | 10 | 15 | 10/5/0 | 0.667/1.000/0.800 | 3.9/3.3/9.4 | 50.7/7.6/404.0 | 50.7 |
| chords | basic_pitch | 10 | 22 | 9/13/1 | 0.409/0.900/0.563 | 5.5/5.5/7.1 | 187.4/149.3/532.1 | 187.4 |
| isolated | bytedance | 4 | 6 | 4/2/0 | 0.667/1.000/0.800 | 2.7/2.2/6.2 | 435.0/60.0/1606.1 | 435.0 |
| isolated | basic_pitch | 4 | 16 | 4/12/0 | 0.250/1.000/0.400 | 16.6/12.9/40.3 | 849.8/766.6/1844.6 | 849.8 |
| long | bytedance | 5 | 7 | 4/3/1 | 0.571/0.800/0.667 | 9.8/8.0/15.9 | 5151.5/4046.5/12053.0 | 5151.5 |
| long | basic_pitch | 5 | 23 | 4/19/1 | 0.174/0.800/0.286 | 18.9/13.5/43.3 | 3352.3/3209.9/6946.4 | 3352.3 |
| music | bytedance | 518 | 576 | 476/100/42 | 0.826/0.919/0.870 | 13.6/10.2/49.3 | 283.7/141.8/2679.1 | 110.1 |
| music | basic_pitch | 518 | 349 | 286/63/232 | 0.819/0.552/0.660 | 15.1/12.3/48.8 | 167.5/105.7/2364.9 | 231.8 |
| repeated | bytedance | 45 | 73 | 44/29/1 | 0.603/0.978/0.746 | 11.4/9.8/39.8 | 74.4/24.1/1669.0 | 74.4 |
| repeated | basic_pitch | 45 | 40 | 36/4/9 | 0.900/0.800/0.847 | 8.2/6.5/21.1 | 196.8/168.2/475.2 | 196.8 |
| sustain | bytedance | 3 | 3 | 3/0/0 | 1.000/1.000/1.000 | 9.2/5.6/19.3 | 701.8/128.0/1853.0 | 600.5 |
| sustain | basic_pitch | 3 | 12 | 3/9/0 | 0.250/1.000/0.400 | 15.1/9.8/33.7 | 568.3/402.4/1207.7 | 576.1 |

Per bestand en aanvullende categorieflags (early/late, grensends, >250/500/1000 ms) staan in results.csv. Elke TP/FN/FP met pitch en raw timing staat in note-results.csv.

## Lange noten en sustain

Alle vier gematchte lange ByteDance-noten eindigen door de upstream **600-frame / ongeveer zes seconden cap**, niet door de adapter. De 3,587 s hoge noot (pitch 105) is volledig gemist; voorspelde pitches 103 en 104 zijn FP. Er is **geen correcte lange ByteDance-noot binnen ±50 ms** in deze subset: een correct voorbeeld kan dus niet eerlijk worden getoond. Basic Pitch treft de 12 s nootduur wel binnen 43 ms; beide engines hebben andere ernstige long-fouten.

| Case | Engine | Pitch | GT onset | Key release | Pedal release | Pred end | Key error s | Effective error s | Match |
|---|---|---|---|---|---|---|---|---|---|
| 05_long | bytedance | 105 | 0.517 | 4.104 | 4.104 | None | None | None | FN |
| 05_long | basic_pitch | 105 | 0.517 | 4.104 | 4.104 | None | None | None | FN |
| 06_long | bytedance | 95 | 0.523 | 6.060 | 6.060 | 6.520 | 0.460 | 0.460 | TP |
| 06_long | basic_pitch | 95 | 0.523 | 6.060 | 6.060 | 1.149 | -4.911 | -4.911 | TP |
| 07_long | bytedance | 82 | 0.517 | 8.595 | 8.595 | 6.510 | -2.085 | -2.085 | TP |
| 07_long | basic_pitch | 82 | 0.517 | 8.595 | 8.595 | 1.649 | -6.946 | -6.946 | TP |
| 08_long | bytedance | 62 | 0.514 | 12.508 | 12.508 | 6.500 | -6.008 | -6.008 | TP |
| 08_long | basic_pitch | 62 | 0.514 | 12.508 | 12.508 | 12.465 | -0.043 | -0.043 | TP |
| 09_long | bytedance | 31 | 0.514 | 18.563 | 18.563 | 6.510 | -12.053 | -12.053 | TP |
| 09_long | basic_pitch | 31 | 0.514 | 18.563 | 18.563 | 17.054 | -1.509 | -1.509 | TP |
| 13_sustain | bytedance | 48 | 0.721 | 2.716 | 2.923 | 2.844 | 0.128 | -0.079 | TP |
| 13_sustain | basic_pitch | 48 | 0.721 | 2.716 | 2.923 | 2.811 | 0.095 | -0.112 | TP |
| 14_sustain | bytedance | 67 | 0.718 | 2.722 | 2.919 | 2.846 | 0.124 | -0.073 | TP |
| 14_sustain | basic_pitch | 67 | 0.718 | 2.722 | 2.919 | 3.124 | 0.402 | 0.205 | TP |
| 15_sustain | bytedance | 90 | 0.718 | 2.717 | 2.920 | 4.570 | 1.853 | 1.650 | TP |
| 15_sustain | basic_pitch | 90 | 0.718 | 2.717 | 2.920 | 1.509 | -1.208 | -1.411 | TP |

De drie losse sustaincases hebben onafhankelijke CC64-down/up. ByteDance matcht alle drie zonder FP; twee ends liggen circa 73–79 ms vóór pedaalrelease, de hoge noot 1,65 s erna. Pedal-extended release betekent hier release volgens MIDI-eventvolgorde en same-pitch-reattackregels van de bestaande parser; dit is **geen meting van volledige akoestische uitsterving**. In muziek verklaren veel late key offsets een vrijwel juiste pedaalrelease, terwijl de cap en andere late releases daar niet door worden verklaard.

## Concrete model → decoder → adapter traces

Raw segmentheads, gedeframede output en upstream events zijn extern gecachet. Elke gespiegeld verklaarde decoderbeslissing is vergeleken met de geïnstalleerde upstream decoder; upstream onset/end wordt vervolgens vergeleken met canonical output. Review.json bevat geselecteerde traces, offsetpeaks, frameactivatie en offsethead bij key/pedal/end/B-landmarks. Hieronder minstens twee echte late en twee vroege gevallen, plus sustain/repeated/akkoord en B-regressies.

| Selectie | Case/pitch | Key / pedal s | Upstream / canonical s | Decoder | First offset/frame-disappear | B end s | Clipped |
|---|---|---|---|---|---|---|---|
| late | 12_repeated/89 | 4.5340/4.5340 | 10.0000/6.2030 | sequence_end | 619/None | 6.1944 | True |
| late | 15_sustain/90 | 2.7170/2.9200 | 6.7100/4.5700 | six_second_cap | 284/None | 2.8432 | True |
| early | 09_long/31 | 18.5630/18.5630 | 6.5100/6.5100 | six_second_cap | None/None | 6.5100 | False |
| early | 08_long/62 | 12.5080/12.5080 | 6.5000/6.5000 | six_second_cap | 54/None | 0.5424 | False |
| sustain | 15_sustain/90 | 2.7170/2.9200 | 6.7100/4.5700 | six_second_cap | 284/None | 2.8432 | True |
| repeated | 12_repeated/89 | 0.8690/0.8690 | 1.2000/1.2000 | next_onset | 88/None | 0.8778 | False |
| chords | 17_chords/62 | 1.5200/1.5200 | 1.5500/1.5500 | frame_disappearance | 57/155 | 0.5735 | False |
| B_correct_cut | 02_isolated/60 | 2.5220/2.5220 | 2.5500/2.5500 | frame_disappearance | 56/255 | 0.5632 | False |
| B_sustain_regression | 24_music/55 | 9.3618/9.9738 | 9.9800/9.9800 | next_onset | 923/None | 9.2349 | False |

De 18,049 s noot eindigt upstream/canonical op 6,510 s; de offsethead heeft pas een geaccepteerde peak op 17,225 s. De cap verhindert dat die deze noot beëindigt. Bij de 11,994 s noot wordt een peak al op 0,542 s geaccepteerd terwijl frameactivatie blijft staan; A eindigt door de cap op 6,500 s, B kiest die vroege peak en beschadigt de noot verder. Dit bevestigt echte-audio decoderlimieten en toont tegelijk waarom ‘eerste peak altijd gebruiken’ geen algemene fix is.

Het repeated-voorbeeld eindigt upstream in gepadde output via sequence_end en wordt door de bestaande adapter op echte audioduur geclipt; dit behoudt te lange canonical timing. Padding en decoder zijn observeerbaar, maar zijn hier niet gewijzigd.

## Policy B: uitsluitend offline

Ongewijzigde policybron SHA256 `f6e1d8b8a311e0e23b2c84f9451b1aa91cf50758dafd267b45dca55e2446814e`. Alleen B-resultaat gebruikt, zonder C/D-scoring of silence bound. GT wordt pas **na** B-berekening aan diagnostiek gekoppeld. Pitch/onsets/TP/FP/FN zijn identiek aan A.

| Categorie | Key MAE A/B ms | Key mediaan A/B ms | Key max A/B ms | Effective MAE A/B ms | Key beter/slechter | Effective beter/slechter | Nieuw early / correct key cut / sustainregressie |
|---|---|---|---|---|---|---|---|
| chords | 50.7/203.1 | 7.6/11.1 | 404.0/946.4 | 50.7/203.1 | 0/2 | 0/2 | 2/2/0 |
| isolated | 435.0/1003.4 | 60.0/1020.3 | 1606.1/1958.8 | 435.0/1003.4 | 0/2 | 0/2 | 2/1/0 |
| long | 5151.5/6640.9 | 4046.5/7025.3 | 12053.0/12053.0 | 5151.5/6640.9 | 0/1 | 0/1 | 0/0/0 |
| music | 283.7/288.9 | 141.8/143.1 | 2679.1/2679.1 | 110.1/128.4 | 24/21 | 10/35 | 25/14/19 |
| repeated | 74.4/109.6 | 24.1/42.9 | 1669.0/1660.4 | 74.4/109.6 | 5/13 | 5/13 | 14/10/0 |
| sustain | 701.8/126.2 | 128.0/126.3 | 1853.0/128.0 | 600.5/76.1 | 1/0 | 1/0 | 1/0/0 |
| TOTAL | 301.8/324.1 | 117.1/128.0 | 12053.0/12053.0 | 148.5/182.6 | 30/39 | 16/53 | 44/27/19 |

B verandert 73 gescoorde voorspellingen: 69 gematchte noten en vier FP. Key-release wordt beter bij 30 en slechter bij 39 matches; effectieve release beter bij 16 en slechter bij 53. ‘Nieuw early’ betekent B >50 ms vóór **effectieve** GT-release terwijl A dat niet was: 44 noten. Daarvan los gerapporteerd 27 eerder correcte fysieke releases die B te vroeg afbreekt en 19 sustainregressies (>50 ms extra effectieve fout). Deze groepen overlappen en mogen niet worden opgeteld. Alle 69 veranderde matches staan in policy-b-changes.csv.

B verbetert de hoge sustainnoot, maar dat compenseert de beschadiging van correcte repeated/chord/muzieknoten niet. Overall key MAE **301,8 → 324,1 ms**; effective MAE **148,5 → 182,6 ms**. Beslissing: **B DO NOT SHIP** als algemene offsetfix.

## CPU-performance en reproduceerbaarheid

| Engine | Inferentie totaal s | Model load s | Peak process RSS MiB | Versies |
|---|---|---|---|---|
| bytedance | 317.450 | 3.050 | 856.2 | {'numpy': '1.26.4', 'librosa': '0.11.0', 'soundfile': '0.14.0', 'mir_eval': '0.8.2', 'piano-transcription-inference': '0.0.6', 'torch': '2.7.1+cpu', 'torchlibrosa': '0.1.0'} |
| basic_pitch | 5.719 | 1.534 | 515.8 | {'numpy': '1.26.4', 'librosa': '0.11.0', 'soundfile': '0.14.0', 'mir_eval': '0.8.2', 'basic-pitch': '0.4.0', 'tensorflow': '2.15.0'} |

Windows CPU, bestaande Python 3.11.9 omgeving. Modellen één keer geladen per engine, clips sequentieel; adapters onveranderd. Runtime omvat transcribe + canonical validatie, exclusief model-load, diskcache en rapportage. Totaal inclusief model-load: ByteDance circa 320,5 s, Basic Pitch 7,3 s. Dit is een warme lokale benchmark, geen cold HTTP-joblatentie en geen hardware-onafhankelijke snelheidsclaim. RSS is elke 100 ms gesampled voor het hele proces; tussenliggende pieken kunnen worden gemist. CPU-threads/defaults zijn niet aangepast. Per-clip timing staat in CSV; SHA256 van audio, modelbestanden, adapter/upstreamcode en versies staat in elke externe provenance.json.

Zie README.md voor download, checksum, externe paden, frozen manifest, modelruns en offline replay. Cache met afwijkende audio/engine/model/artifacts wordt geweigerd; gebruik dan een nieuwe outputdirectory, overschrijf geen eerdere run.

## Beperkingen en besluit

24 cases, één fysieke piano/microfoonconditie, vijf korte muziekfragmenten; muziek draagt 518/585 labels bij. Geen volledige datasetbenchmark, geen gecontroleerde achtergrondruisvergelijking, geen menselijke liveperformance en geen velocitykwaliteitclaim. Native pre-roll RMS is alleen diagnostisch gemeten; geen causaliteitsclaim over ruis. Hoge pitch 105 en lange-notencap zijn echte beperkingen. Alle raw metrics gebruiken onafhankelijke MIDI-labels zonder shifts of tuning.

**BYTEDANCE READY WITH KNOWN OFFSET LIMITATION**: de hogere pitch/onset-recall en F1 ondersteunen ByteDance als primaire engine, met menselijke correctie voor de stagedemo. Lange nootduren zijn aantoonbaar onbetrouwbaar. **B DO NOT SHIP**. Aanbevolen volgende stap, alleen na beoordeling: een begrensd decoderonderzoek naar de zes-seconden-cap, met deze bevroren set als regressiecontrole en aparte aandacht voor sustain/repeated. Geen globale first-offsetpolicy invoeren.

## Tests en worktree

61 relevante tests geslaagd (MAPS 15, bestaande benchmark/ByteDance/policies samen 46), drie bestaande deprecationwarnings. De eerste testrun onder standaard Windows-temp faalde bij testfixture-setup door tempdirectoryrechten; een expliciete verse tempdirectory binnen de chatworkspace verhelpt dit zonder codewijziging. De bestaande uploadbug is buiten deze offline validatie gelaten. Geen commit/stage/push. Vooraf bestaande 105 Git-zichtbare bestanden worden met SHA256 gecontroleerd op ongewijzigde inhoud; volledige git-status wordt afzonderlijk geleverd.
