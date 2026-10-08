# ByteDance offset-policy-experiment — 7 oktober 2026

> Historisch rapport. De beperkte synthetische winst hieronder is later
> onvoldoende gebleken: Policy B/C zijn **DO NOT SHIP** als algemene fixes.
> Huidige stagedemo: ByteDance + menselijke correctie + bekende offsetbeperking;
> **KEEP CURRENT CAP**. Zie `../maps/maps-enstdkcl-validation.md` en
> `../maps/maps-long-note-cap-diagnosis.md`. Meetwaarden blijven ongewijzigd.

## Uitkomst

**C (hybride) wint dit beperkte experiment:** gemiddelde absolute offsetfout
tegen fysieke key release daalt van **890,714 naar 520,131 ms (41,6%)**.
Zes van 23 offsets verbeteren, geen enkele verslechtert. Alle policies behouden
exact dezelfde 23 pitches/onsets, TP=23, FP=0, FN=0, F1=1,000 en onset-MAE=3,748 ms.

Dit is geen vrijbrief voor een algemene productiefix. De guard geeft slechts een
akoestische bovengrens bij exacte digitale eindstilte. Pedaalvoorspelling mist
het echte pedaalinterval in onze sustainclip. Een geldige maar verkeerde vroege
offsetpiek kan een lange of sustainnoot te vroeg stoppen; deze dataset bevat
geen geval dat dat risico voldoende uitsluit. Productieadapter en dependency
zijn ongewijzigd. Er is niets gecommit of gepusht.

## Bevroren baseline en herkomst

Uitsluitend `single_notes` (4), `melody_repeated` (8), `overlapping_chords` (6)
en `long_notes_sustain` (5) uit `20261006-baseline-01`: 23 vooraf geschreven
MIDI-referentienoten en dezelfde synthetische piano-WAVs, FluidSynth/TimGM6mb.
Geen nieuwe audiovoorbeelden of thresholdtuning. Geen onafhankelijke annotatie
van akoestische resonantie; fysieke key release en MIDI-CC64-verlengde release
zijn verschillende targets.

ByteDance `piano-transcription-inference==0.0.6`, hetzelfde Note_pedal-checkpoint,
CPU, onset/offset/frame/pedal-offsetthresholds 0.3/0.3/0.1/0.2. Checkpoint SHA256:
`c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141`.

Voor single_notes en long_notes_sustain zijn de opgeslagen raw/decoded heads uit
`offset-diagnosis-20261006` letterlijk hergebruikt. Voor melody_repeated en
overlapping_chords bestonden wel baseline-events, maar geen opgeslagen heads;
alleen die twee identieke bevroren WAVs zijn opnieuw door de ongewijzigde
productiebinding gehaald. Normalisatie van alle vier outputs reproduceert de
oorspronkelijke canonical notes **exact**, inclusief floats/confidence/velocity.
De decodertrace is event voor event gecontroleerd tegen upstream. Dezelfde
upstreambronhashes als de diagnose worden vereist.

Raw heads, binarized heads, upstreamevents, bron/audiomodelhashes en cacheherkomst
staan gitignored onder `backend/data/benchmarks/runs/offset-policy-frozen-heads/`.
Het machineleesbare resultatenbestand bevat die hashes en de policybronhash.
Een volgende run gebruikt deze cache, zonder inferentie of modelinitialisatie.

## Candidate policies: exacte logica

De regels zijn vastgelegd vóór scoring. Policyhelpers ontvangen alleen events,
decoderstate, modelheads, resampled audioduur, volgende **voorspelde** onset van
dezelfde pitch, **voorspelde** pedaalintervallen en een native audio-stiltebound.
Ground-truth key/pedal release is nergens policyinput. Referentie-MIDI wordt
alleen voor scoring gedecodeerd nadat alle runtimebeslissingen berekend zijn;
vooraf worden uitsluitend bestandshashes gecontroleerd.

**A — huidige baseline.** Behoud exacte upstream decoded events. Voor scoring
volgt de bestaande adapterregel `min(upstream_end, resampled_audio_duration)`.
Dit is precies de canonical baseline van de oorspronkelijke benchmark.
De CSV bewaart de ongeclipte upstream end afzonderlijk, zodat een wijziging niet
verward wordt met het bestaande clippingeffect. Geen nieuwe decoder voor A.

**B — offsetpiekvoorkeur.** Kies de eerste upstream reeds geaccepteerde offsetpiek
van dezelfde pitch, strikt na onset, op/voor min(upstream end, audioduur) en strikt
vóór een volgende same-pitch onset. Upstream's bestaande offsetthreshold 0.3,
monotonic neighbour=4 en parabolische shift blijven exact gelijk. Geen nieuwe
lokale-maximafilter of piekscorethreshold. Een piek binnen een voorspeld
pedaalinterval wordt overgeslagen; de policy zoekt dan de volgende bruikbare
piek. Zonder bruikbare piek: A. Als upstream al dezelfde piek koos, behoud zijn
float32 event exact; CSV toont de raw parabolische timestamp apart. Andere
pitches/chord-onsets begrenzen de noot niet.

**D — afzonderlijke runaway-guard.** Signaleer uitsluitend upstreambeslissingen
`six_second_cap` of `sequence_end`. Een zes seconden lange noot wordt niet op
grond van zijn duur alleen als fout bestempeld. Bij zo'n boundary-event wordt
A uitsluitend verkort wanneer de native WAV in alle kanalen eindigt met exacte
digitale nullen: de grens is het eerste sample na het laatste niet-nul sample.
Die grens moet strikt na onset en vóór A liggen. Geen amplitude-epsilon,
arbitraire maximale nootduur of nieuw stiltevenster. Zonder dat bewijs: A en
alleen een boundary-vlag. Normale frame-disappearance/offset/reattack-events
worden niet door D veranderd, ook niet als ze later in padding eindigen.

**C — hybride.** B indien een bruikbare piek bestaat, anders D; D valt zonder
bewijs terug op A. Geen extra heuristiek of parameterzoektocht.

## Metingen over alle 23 noten

Bestaande één-op-één mir_eval matching: dezelfde integer pitch, onset <=50 ms,
offset niet betrokken bij primaire matching. Onsets/count/pitches moeten exact
gelijk blijven; dit wordt daarnaast direct geassert. Timingfouten worden over
dezelfde 23 matches gemeten. Alle tijden hieronder zijn milliseconden.

| Policy | TP / FP / FN | Pitch/onset F1 | Onset-MAE | Key offset-MAE | Key mediaan | Grootste key-fout | Gewijzigd | Beter / slechter |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A huidig | 23 / 0 / 0 | 1,000 | 3,748 | 890,714 | 180,000 | 3907,375 | 0 | 0 / 0 |
| B piek | 23 / 0 / 0 | 1,000 | 3,748 | 703,183 | 40,000 | 3907,375 | 4 | 4 / 0 |
| C hybride | 23 / 0 / 0 | 1,000 | 3,748 | 520,131 | 40,000 | 2640,000 | 6 | 6 / 0 |
| D guard | 23 / 0 / 0 | 1,000 | 3,748 | 707,662 | 180,000 | 3214,000 | 2 | 2 / 0 |

“Beter/slechter” vergelijkt absolute key-releasefout met A; verschillen <=0,1 µs
tellen niet als wijzigingen. Geen modeltolerance of tuningparameter.
Pitch-only en onset-only hebben eveneens afzonderlijk TP=23/FP=0/FN=0/F1=1.
Offset-F1 met dezelfde eerdere max(50 ms, 20% key-nootduur) is A/D=0,478261 en
B/C=0,608696; dit is een afzonderlijke score, geen wijziging van pitch/onset-F1.

| Policy | Offset-MAE t.o.v. pedal-release, alle 23 | Exact aan audioduur | Exact aan 10 s segmentgrens | Herkende decoder-boundarycases |
|---|---:|---:|---:|---:|
| A | 727,670 | 3 | 0 | 2 |
| B | 540,140 | 2 | 0 | 2 |
| C | 357,088 | 0 | 0 | 2 |
| D | 544,618 | 1 | 0 | 2 |

De 10 s segmentgrens is niet de 600-framegrens: de twee cap-events zijn op
7,400 en 9,910 s gedecodeerd. Audioduur-counts zijn exacte canonical eindtijden,
geen afronding op frames. Alleen twee cases zijn aantoonbare cap/sequence-events;
de D4 die in padding door frame-disappearance eindigt blijft terecht buiten D.

### Sustain: de drie daadwerkelijk door CC64 verlengde referentienoten

| Policy | Key-release-MAE | Pedal-release-MAE | Slechter dan A t.o.v. pedal-release |
|---|---:|---:|---:|
| A | 2610,428 | 1360,428 | 0 |
| B | 2610,428 | 1360,428 | 0 |
| C | 1937,501 | 687,501 | 0 |
| D | 1937,501 | 687,501 | 0 |

B verandert geen van deze drie sustainnoten: C4 heeft geen bruikbare piek,
E4 behoudt zijn huidige piek rond pedal-up, G4 heeft geen bruikbare piek.
C/D verbeteren alleen G4 door een globale akoestische bound. Het model voorspelt
hier alleen een fout vroeg pedaalinterval 0,020–0,190 s en **mist het echte
3,000–5,000 s interval**. Afwezigheid van een pedaalvoorspelling is dus geen bewijs
dat sustain afwezig is. De beschermregel is deterministisch getest, maar deze
drie raw voorbeelden bewijzen niet dat B veilig is bij een vroege key-releasepiek
onder werkelijk sustain. Pedal-extended release omvat bovendien geen SoundFont
release-resonantie na pedal-up.

### Runawaycases: twee beslissingen door de 600-framegrens

Key-offset-MAE van F4 (65) en sustain-G4 (67): A/B **3560,688 ms**;
C/D **1455,590 ms**. Beide verbeteren, geen verslechtering. Het herkennen van de
capbeslissing is betrouwbaar dankzij upstreamstate; het schatten van de gewenste
muzikale offset is daarmee nog niet opgelost. Alle vier clips zijn korter dan
10 s, één segment; geen geobserveerde sequence_end-case of echte lange held note
voorbij zes seconden. Sequence_end en abstineren zonder stilte worden wel getest.

## Concrete cases en actieve regressiecontrole

Tijden zijn seconden. `—` betekent geen bruikbare geaccepteerde piek in het
policyvenster; het model produceert geen zelfstandige scalar note end.

| Clip / noot | Key release | Pedal release | Raw kandidaat | Upstream end | A | B | C | D |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| single B4 / 71 | 4,000000 | 4,000000 | 3,984769 | 5,010000 | 5,010000 | 3,984769 | 3,984769 | 5,010000 |
| sustain G4 / 67 | 4,150000 | 5,000000 | — | 9,910000 | 8,057375 | 8,057375 | 6,038594 | 6,038594 |
| chord F4 / 65 | 2,800000 | 2,800000 | — | 7,400000 | 6,014000 | 6,014000 | 3,822585 | 3,822585 |
| chord A4 / 69 | 2,800000 | 2,800000 | 2,806421 | 2,806421 | 2,806421 | 2,806421 | 2,806421 | 2,806421 |
| single C4 / 60, correct | 1,000000 | 1,000000 | 0,998586 | 0,998586 | 0,998586 | 0,998586 | 0,998586 | 0,998586 |
| sustain E4 / 64 | 3,750000 | 5,000000 | 5,033910 | 5,033910 | 5,033910 | 5,033910 | 5,033910 | 5,033910 |
| chord D4 / 62 | 2,800000 | 2,800000 | 3,804787 | 7,060000 | 6,014000 | 3,804787 | 3,804787 | 6,014000 |

- **B4:** offsetpiek wordt direct benut in plaats van de frame-disappearance op
  5,010 s. Absolute fout van 1010,000 naar 15,231 ms. D verandert deze normale
  framebeslissing niet.
- **Sustain-G4:** geen piek; cap na 600 frames. Exacte digitale eindstilte begint
  op 6,038594 s. C/D begrenzen daar. Key-fout daalt van 3907,375 naar 1888,594 ms;
  pedal-fout van 3057,375 naar 1038,594 ms. Nog duidelijk te laat, geen gevonden
  correcte key/pedal-release en geen claim over exacte hoorbaarheid.
- **F4 / 65:** eveneens cap, geen geaccepteerde offsetpiek. Bound 3,822585 s
  verbetert 3214,000 naar 1022,585 ms, nog circa één seconde fout.
- **A4 / 69:** reeds correcte piek blijft exact hetzelfde, key-fout 6,421 ms.
  **C4 control** blijft exact hetzelfde, key-fout 1,414 ms.
- **Repeated G4:** eerste noot verandert van 2,090000 naar 1,982025 s voor key
  2,000000; de volgende G4-onset 2,104975 en zijn end 2,420239 blijven behouden.
  Geen samenvoegen/stealen: 8 melody-events blijven 8. De laatste C4 verbetert
  van 4,640000 naar 3,602803 s voor key 3,600000. Alle andere melody-offsets blijven.
- **Overlapping chords:** alleen D4 en F4 veranderen. De eerste akkoordnoten
  C4/E4/G4 blijven helaas rond 2,81–2,84 s eindigen voor key 1,70 s. Een duidelijke
  gemiddelde verbetering verbergt dus nog bestaande fouten van >1 s. De eerste
  geaccepteerde D4-piek 3,804787 s is ook laat; de policy gebruikt hem niet omdat
  ground truth hem “goed” noemt, maar omdat hij runtime bruikbaar is.
- **Correcte lange noten:** de twee lang aangehouden noten (48 en 55) in de
  sustainclip behouden end 2,833733 en 2,835965 s; geen vroege knip. De 48 blijft
  333,733 ms te laat. Een werkelijk correcte held note van >6 s is niet aanwezig.
- **Ruispieken:** geen verslechtering op deze 23 noten. Alleen pieken die upstream
  al accepteert tellen; een hoge raw score zonder de bestaande monotonic peak
  wordt niet opnieuw gedrempeld. Dat biedt geen garantie tegen een foutieve
  geaccepteerde piek. Een afzonderlijke deterministische tegenvoorbeeldtest laat
  bewust zien dat B een correcte lange noot vroeg kan stoppen als zo'n piek
  binnen zijn venster valt; een tweede laat zien dat ontbrekende voorspelde
  sustainbescherming niet kan worden teruggewonnen uit ground truth.
- **Guardrisico:** een echte key kan ingedrukt blijven nadat een sampled instrument
  tot digitale stilte is vervallen. De guard is dan een akoestische bovengrens,
  geen fysieke release. Dat tegenvoorbeeld is expliciet getest. Bij microfoonruis
  zal de exact-zero guard meestal niets veranderen; deze synthetic-tail winst
  is daarom geen aangetoonde winst op echte opnames.

Alle 23 nootregels, signed key-/pedal-fouten per policy, accepted peaks/scores,
decoderredenen, stiltebound en voorspelde pedaalintervallen staan in
`bytedance-offset-policy-notes.csv`. Geen verslechterde offset t.o.v. key release
op de 23; op de drie sustainnoten ook geen verslechtering t.o.v. pedal release.
De bovenstaande tegenvoorbeelden zijn **helpertests**, geen nieuwe benchmarks
of extra ground-truthnoten, en veranderen de 23-nootscores niet.

## Antwoorden en aanbevolen vervolg

1. **Raw offset-output beter benutten?** Ja. B verbetert vier offsets, MAE
   890,714 → 703,183 ms; pitch/onset exact gelijk. Niet iedere head bevat een
   bruikbare piek en niet iedere accepted peak ligt dicht bij key release.
2. **Helpt een kleine hybride?** Ja in deze set. C voegt twee boundarybounds toe,
   MAE 520,131 ms, mediaan 40,000 ms. Dat is nog geen goede eindtijdkwaliteit.
3. **Sustain/correcte noten kapot?** Geen geobserveerde regressie hier. Correcte
   controls, twee langere noten, repeated onsets en het correcte pedal-up-end
   blijven behouden. Ontbrekende pedaaldetectie en verkeerde accepted peaks
   blijven expliciete risico's; tests tonen tegenvoorbeelden.
4. **Runaways betrouwbaar herkennen zonder nieuwe maxduur?** De herkomst
   cap/sequence_end kan exact worden herkend, los van de nootduur. Dat bewijst
   geen muzikale fout. Zonder extra runtimebewijs moet de guard abstineren;
   exacte trailing zeros geven alleen een conservatieve signaalbound.
5. **Kleinste kandidaat voor een eerste productiefix?** **B** is het kleinste
   begrijpelijke kandidaatonderdeel: bestaande geaccepteerde piekvoorkeur met
   runtimevenster en voorspelde pedaalbescherming. **C wint de benchmark**, maar
   zijn aanvullende winst leunt op synthetische exact-zero tails. Ik adviseer
   vóór productie één aparte validatiestap met onafhankelijke sustain- en echt
   lange-nootgevallen: vooral een vroege offsetpiek tijdens sustain, foutieve
   accepted peaks, en held notes voorbij zes seconden. Geen heuristiek aanpassen
   op deze 23 noten. B is daarmee een kandidaat, nog geen bewezen veilige
   algemene fix. De winnende policy is nu nergens in productie toegepast.

## Tests en reproduceerbaarheid

Reproduceren en vaste policyregels: `../experiments/offset_policy/README.md`.
Vereiste tests: offset-policies, bestaande benchmarkmetrics, ByteDance-adapter
en decoderdiagnose. Bestaande testverwachtingen zijn niet aangepast. Tests
dekken bruikbare/onbruikbare pieken, predicted sustain, cap/sequence-boundaries,
abstineren zonder stille staart, normale correcte noten, float32/float64
piekidentiteit, repeated onset-venster, andere chordpitch, exact-zero stereo,
en drie expliciete beperkingen/tegenvoorbeelden.

**52 tests geslaagd**, waaronder 19 policytests, 15 benchmarktests, 12
ByteDance-adaptertests en 6 decoderdiagnosetests. Drie bestaande
FastAPI/Starlette-deprecationwarnings. Geen volledige backend- of frontendrun:
productie en frontend zijn niet gewijzigd; de gevraagde relevante suites zijn
uitgevoerd. De bekende Windows-uploadtest staat buiten dit experiment en is
niet aangepast.

Alleen nieuwe experimenthelpers/tests/rapporten zijn toegevoegd. 74 bestanden
(applicatiebron, upstreambron, baseline-output, referentie-MIDI/metadata en WAVs)
zijn via voor-/nahashes gecontroleerd: geen veranderingen. Dependencyconfig
is niet gewijzigd. Geen commit, push, staging of policyactivatie.
