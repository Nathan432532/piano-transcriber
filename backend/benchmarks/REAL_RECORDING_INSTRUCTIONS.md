# Echte piano opnemen met onafhankelijke MIDI-reference

> Historische opnamehandleiding van vóór MAPS. De datasetvalidatie is inmiddels
> uitgevoerd: **BYTEDANCE READY WITH KNOWN OFFSET LIMITATION**, Policy B/C
> **DO NOT SHIP**, **KEEP CURRENT CAP**. Zie `maps/maps-enstdkcl-validation.md`
> en `maps/maps-long-note-cap-diagnosis.md`. De onderstaande nul beschikbare
> cases en MORE VALIDATION-status beschrijven alleen de eerdere inventarisatie.
> Nieuwe persoonlijke opnames zijn optioneel vervolgwerk, geen checkpointvereiste.

Status op 7 oktober 2026: **MORE VALIDATION NEEDED**. Er zijn geen geschikte
gelijktijdige MIDI+audio-recordings gevonden. Deze procedure bereidt de volgende
validatie voor; er is geen nieuwe modelrun, offsetpolicy of importfunctie gestart.

## Wat ontbreekt en wat je nodig hebt

We hebben per performance nodig: een onbewerkte microfoonopname én rechtstreeks
opgenomen MIDI-events van **dezelfde gespeelde toetsen en hetzelfde pedaal**.
MIDI uit een transcriber of een later nagespeelde performance is geen reference.

Voor bewezen **akoestische** validatie moet het geluid van echte pianostrings
komen, bijvoorbeeld een akoestische/hybride piano met gelijktijdige MIDI-uitvoer
of een onafhankelijk sensorsysteem. Een gewone akoestische piano zonder zo'n
systeem geeft niet vanzelf MIDI. Speel de audio en MIDI niet op twee verschillende
instrumenten en schrijf geen gewenste MIDI achteraf als labels.

Heb je alleen een digitale piano/keyboard met MIDI, dan kun je zijn luidsprekers
met een microfoon opnemen. Dat is een nuttige echte opname met roomnoise en
onafhankelijke key-events, maar het instrumentgeluid is elektronisch. Vul dan
`digital_piano_speaker_microphone` in; dit bewijst niet automatisch prestaties op
een akoestische vleugel. Directe line-out, VST- of SoundFont-rendering houden we
eveneens apart. Heb je alleen een akoestische piano en telefoon, bewaar de audio
als ongelabelde diagnostiek; daar hangen we geen precision/recall aan.

Benodigd: instrument met MIDI-out/USB-MIDI, computer met een programma dat audio
en MIDI tegelijk kan opnemen, microfoon of audio-interface, sustainpedaal voor
case 06. Een telefoon kan als afzonderlijke audiorecorder dienen, met de
synchronisatiecontrole verderop. Je bestaande opnameprogramma is prima.

## 1. Neem zeven korte performances op

Elke case is één nieuwe take met audio én MIDI. Case 08 is optioneel. De tijden
hieronder zijn ongeveer inclusief sync-noten en uitklinken. Het gaat niet om
precies spelen: de werkelijk geregistreerde MIDI-events zijn de reference.
**C4 betekent MIDI-pitch 60**; octaafnamen kunnen in opnameprogramma's verschillen.

| Mapnaam | Ongeveer | Wat spelen | Pedaal |
|---|---:|---|---|
| `01_single_notes` | 25–30 s | 8 losse noten: C3(48), G3(55), C4(60), E4(64), G4(67), C5(72), E5(76), C6(84). Houd elke toets circa 0,5 s vast en laat een duidelijke pauze. | uit |
| `02_melody` | 25–30 s | 12 rustige noten: C4 D4 E4 G4 E4 D4 C4 C5 B4 A4 G4 E4. Circa één aanslag per seconde, verschillende releases. | uit |
| `03_repeated_notes` | 20–25 s | G4 acht keer; eerst rustig, daarna sneller. Laat de toets telkens echt los. | uit |
| `04_chords` | 25–30 s | C4+E4, C4+E4+G4, D4+F4+A4. Laat bij één akkoord de toetsen na elkaar los; voeg één overlappende nieuwe noot toe. | uit |
| `05_long_notes` | 40–45 s | C4 circa 4 s, E4 circa 5,5 s, G4 circa 7,5 s vasthouden; 2 s pauze tussen de noten. Laat de toets tijdens het vasthouden niet los, ook als het geluid zacht wordt. | uit |
| `06_sustain` | 30–40 s | Voer de drie onderdelen uit de sustainprocedure hieronder uit. | bewust wisselen |
| `07_mixed_phrase` | 25–35 s | Een natuurlijke frase van circa 12–20 noten: losse noten, herhalingen en een akkoord. | noteer of je het gebruikt |
| `08_fast_overlap` | 20–30 s | Optioneel: kort arpeggio of snellere passage met overlap, circa 15–25 noten. | liefst uit |

## 2. Audio en MIDI tegelijk registreren

De eenvoudigste tijdlijn is één opnameproject met twee gewapende tracks:
microfoonaudio en MIDI-input van de piano. Neem beide in één recordactie op.
Geen quantization, MIDI-inputcorrectie, effecten, noise gate, normalisatie,
auto-trim, tempo-wijzigingen of automatisch verplaatsen van items.

Concreet voorbeeld met REAPER, als je dat gebruikt:

1. Kies in de voorkeuren de microfoon/audio-interface en schakel de MIDI-input
   van de piano in. Maak twee tracks en noem ze AUDIO en MIDI.
2. Selecteer op AUDIO de microfooninput; op MIDI de piano-input met alle kanalen.
   Neem inputs op, geen synthoutput. Schakel beide recordknoppen in.
3. Sla het project op. Zet de cursor op projecttijd 0 en start één opname.
4. Controleer eerst een korte oefentake: audio bevat de piano; MIDI bevat
   note-on, note-off en bij pedaalgebruik CC64. Bewaar ook de oorspronkelijke
   opnamebestanden en het project.

Deze bediening is gebaseerd op de officiële
[REAPER Quick Start](https://www.reaper.fm/guides/REAPER%20Quick%20Start.pdf).
De overige opname- en validatieregels hier zijn ons eigen protocol.

Plaats de microfoon op een vaste plek, bijvoorbeeld ongeveer een meter van de
piano. Noteer de afstand. Kies een vast opnameniveau waarop harde aanslagen niet
clippen; laat wat headroom. Zet een metronoom alleen op hoofdtelefoon als je die
nodig hebt. Geen klik, ander instrument of MIDI-synth door de microfoon laten
meeklinken. Neem gewoon aanwezige zachte roomnoise mee; verwijder die niet.

## 3. Begin en eindig iedere take met dezelfde sync-noten

1. Start audio en MIDI en wacht circa 2 s, zonder pedaal.
2. Speel drie geïsoleerde C5's (pitch 72), kort en duidelijk, circa 1 s uit elkaar.
3. Wacht 2 s en speel de eigenlijke case.
4. Laat na de case het pedaal los en wacht tot de piano grotendeels uitklinkt.
5. Speel opnieuw drie geïsoleerde C5's, zonder pedaal, circa 1 s uit elkaar.
6. Neem daarna nog minimaal 3 s uitklinken/roomnoise op en stop beide tracks.

Dezelfde aanslagen zijn hierdoor zichtbaar in onafhankelijke MIDI én in de
waveform. Een handklap alleen is onvoldoende: die heeft geen MIDI-event.
De sync-noten blijven in de originele bestanden staan. Noteer de start/eindtijd
van de muzikale case tussen deze blokken. Bij scoring sluiten we sync-blokken
voor **beide** engines en de reference op dezelfde vooraf vastgelegde manier uit,
door onset binnen het casevenster te selecteren. We knippen geen nootends af aan
dat venster. Dit venster mag niet worden gekozen op basis van modelpredictions.

## 4. Zo testen we sustain

Begin met pedaal omhoog; leg alle CC64-events rechtstreeks vast.

- **Losse sustainnoot:** pedaal indrukken, C4 aanslaan, toets na circa 0,7 s
  loslaten, pedaal nog circa 3 s ingedrukt houden en dan loslaten. Neem het
  uitklinken op.
- **Sustainakkoord:** pedaal indrukken, C4+E4+G4 spelen, toetsen na circa 1 s
  loslaten, pedaal nog circa 3 s vasthouden en loslaten.
- **Sustain met reattack:** pedaal indrukken, G4 kort spelen/loslaten, circa
  1 s later opnieuw G4 spelen/loslaten en daarna het pedaal loslaten.

Drie verschillende dingen blijven afzonderlijk: MIDI key release, pedal-up en
het hoorbare uitklinken. MIDI note-off mag niet automatisch naar pedal-up worden
verplaatst. Bewaar continue CC64-waarden als het pedaal die levert. Voor de
bestaande scorer geldt CC64 >=64 als down en <64 als up; een same-pitch reattack
beëindigt de eerdere logisch pedal-held reference bij die nieuwe onset. Dat is
een scoringsconventie, geen meting van het einde van stringresonantie.

Controleer in de oefentake dat CC64 werkelijk wordt opgenomen. Ontbreekt CC64,
dan kunnen we key releases scoren maar geen betrouwbare pedal-extended-release
claim doen. Vul ontbrekende pedaalevents niet achteraf uit modeloutput aan.

## 5. Bestanden en export

Plaats ze onder deze projectmap; maak per case één map:

`<repo>\backend\data\ground_truth\real_recordings\originals\`

Voorbeeld:

```text
originals/
  01_single_notes/
    audio.wav
    performance.mid
    metadata.json
    session.rpp                 # of het native project van jouw programma
    recorder-original.m4a       # alleen indien dit het telefoonorigineel is
  02_melody/
    audio.wav
    performance.mid
    metadata.json
    session.rpp
  ...
```

- **Audio:** bij voorkeur WAV PCM24, 44,1 of 48 kHz, mono of stereo. PCM16 is ook
  bruikbaar. Geen MP3-export of automatische normalisatie. Behoud sample rate,
  kanaalindeling, stilte en volledige uitklinkstaart.
- **MIDI:** Standard MIDI File type 0 of type 1 (`.mid`), met werkelijk
  gespeelde note-on/off, velocity, originele timing/tempo-map en CC64. Geen type 2,
  piano-roll-bewerkingen, quantization of export van een modelsynthese.
- **Gemeenschappelijke tijdnul:** audio én MIDI exporteren vanaf dezelfde
  projecttijd 0, inclusief de aanloop en sync-noten. Gebruik dezelfde projectbounds
  en voldoende tijd na het laatste MIDI-event; audioduur mag langer zijn dan de
  laatste MIDI-noot. Exporteer MIDI niet als los item dat naar tijd 0 wordt verschoven.
- **Originelen:** behoud de native sessie en alle oorspronkelijke recorderfiles.
  Een export/conversie is een apart bestand; overschrijf de oorspronkelijke take niet.

In REAPER: audio via render van alleen de microfoontrack; kies bounds vanaf
projecttijd 0 en WAV. MIDI via **File → Export Project MIDI**, gehele project,
alleen de MIDI-track, type 0/1 met tempo-map. Controleer beide exports in een
nieuw leeg project: begin-sync en eind-sync moeten hun oorspronkelijke relatieve
positie behouden. Zie de officiële
[REAPER User Guide](https://www.reaper.fm/userguide.php), onderdeel Exporting Project MIDI.

Bij telefoonopname: start de telefoon vóór de computeropname. Gebruik een
recorder die bij voorkeur WAV bewaart. Heb je alleen M4A, behoud dat origineel;
eventuele latere PCM-conversie komt onder `derived/`, nooit over het origineel.
Noteer dit in metadata. Geen afzonderlijk opgenomen nagespeelde MIDI gebruiken.

## 6. Vul per take eenvoudige metadata in

Kopieer dit voorbeeld naar `metadata.json`. Vervang tekst tussen haakjes.
`null` betekent onbekend/nog niet gemeten, niet nul. Dit is een documentatievoorbeeld,
geen geïmplementeerd importschema en geen gefingeerde opname.

```json
{
  "caseId": "01_single_notes",
  "recordedAt": "(datum en lokale tijd, inclusief tijdzone)",
  "instrument": "(merk/model piano)",
  "soundSource": "(acoustic_piano_microphone of digital_piano_speaker_microphone)",
  "microphone": "(microfoon/interface of telefoonmodel)",
  "microphoneDistanceMeters": null,
  "recordingSoftware": "(programma en versie)",
  "audioOriginal": "audio.wav",
  "midiOriginal": "performance.mid",
  "samePerformance": true,
  "midiSource": "direct instrument MIDI input; not model output",
  "sampleRateHz": null,
  "audioDurationSeconds": null,
  "bitDepth": null,
  "channels": null,
  "cc64Recorded": null,
  "noiseDescription": "(rustige kamer, ventilator, verkeer, enz.)",
  "analysisWindowAudioSeconds": null,
  "alignment": {
    "rule": "audio_time = midi_time + offsetSeconds",
    "offsetSeconds": null,
    "method": "(zelfde projecttijdnul, bevestigd met sync-noten; of waveform-sync)",
    "beginSyncMeasurements": [],
    "endSyncMeasurements": [],
    "uncertaintySeconds": null,
    "driftCheck": "not_checked"
  },
  "audioSha256": null,
  "midiSha256": null,
  "notes": "(bijzonderheden; geen audio/MIDI-edits)"
}
```

Je hoeft onbekende technische waarden niet te raden. Als het opnameprogramma
ze niet toont, laat ze leeg; we meten duur/sample rate/checksums uit de bestanden.
De mapnaam, instrumentbron, dezelfde performance en de CC64-controle kun je zelf
wel bevestigen. Voeg de originele opnameprojecten ook toe.

## 7. Uitlijning: één globale offset, geen passende predictions maken

Eerst controleren we tijdnul/export. Bij één DAW is offset 0 het uitgangspunt,
maar sync-noten controleren eventuele MIDI/audio-latency. Bij losse telefoon en
MIDI-recorder moet een verschuiving onafhankelijk worden gemeten.

Gebruik uitsluitend de vooraf gespeelde sync-noten en de originele waveform:
noteer per begin-sync de MIDI-note-on-tijd en het zichtbare begin van de
bijbehorende audioaanslag. Bereken voor elk paar `audioTime - midiTime`; de
mediaan van de drie levert hoogstens **één** globale offset voor die take. Bewaar
de drie meetparen, meetonzekerheid en onderbouwing. Verschuif alle reference
note-on/off en pedaaltijden met dezelfde offset. Predictions worden niet
individueel verschoven en originelen worden niet herschreven.

Controleer de eind-sync met dezelfde offset. Als die niet overeenkomt binnen
de meetonzekerheid, kan er klokdrift of een exportfout zijn. Markeer alignment
dan als onbetrouwbaar en controleer/herhaal de opname; geen time-stretch,
stukgewijze offset, automatische best-F1-shift of verschuiving per noot.
Een globale offset mag niet worden gekozen om het ene model beter te scoren.
Dezelfde uitgelijnde reference geldt voor ByteDance en Basic Pitch.

Nog geen meetgereedschap beschikbaar? Lever de originele bestanden met de
sync-noten aan en laat offset/meetparen `null`/leeg. De afzonderlijke validatiestap
moet deze meting bevestigen **vóór** scoring; een onbekende offset is geen 0.
Akoestische aanlooptijd, MIDI-sensorlatency en perceptueel gekozen audio-aanvang
blijven meetbeperkingen; MIDI key release is geen hoorbare uitsterving.

## 8. Roomnoise en controle vóór aanleveren

Voor een eenvoudige eerste set: houd microfoon, positie en niveau vast, en
registreer de gewone roomnoise. Voor een echte clean/noise-vergelijking is een
tweede gelijktijdige audio-opname van **dezelfde performance** nuttig, met
dezelfde MIDI. Bewaar bijvoorbeeld `audio-near.wav` en `audio-room.wav` en noteer
positie/bron/alignment apart. Verschillen bevatten dan mogelijk ook afstand en
reverb, niet alleen ruis. Een later opnieuw gespeelde noisy take heeft zijn eigen
MIDI en is geen exact gepaarde noiseproef. Voeg nu geen ruis toe of processing toe
aan de originelen; eventuele latere afgeleide noiseproeven worden apart vastgelegd.

Controleer eerst de oefentake en vervolgens iedere case:

- Microfoonaudio bevat piano, is niet overstuurd en bevat begin-/eind-sync.
- MIDI bevat de echte note-on/off; case 06 bevat ook pedaal down/up.
- Audio en MIDI komen aantoonbaar van dezelfde take, met bewaarde sessie.
- Geen quantization, trims, fades, warping, MIDI-correcties of modelgegenereerde labels.
- Pedaal is aan het eind omhoog; audio stopt pas na voldoende uitklinken.
- Bestanden hebben de afgesproken namen en de metadata vermeldt bron/roomnoise.

Daarna kunnen we bestanden importeren/checksummen, alignment bevestigen en
exact dezelfde audio door beide bestaande adapters halen. De huidige benchmark-
matching blijft: één-op-één mir_eval, integer pitch (1-cent tolerance in Hz),
onset <=50 ms; offsets tellen niet mee in primaire TP/FP/FN. Rapportage omvat
precision/recall/F1, onset-MAE/mediaan/max en key-/pedal-offset-MAE/max per case
en categorie. Geen modelcorrecties vóór scoring. ByteDance raw offset,
canonical clipping en echte audioduur worden afzonderlijk bekeken.

## Wat nu beschikbaar is — nog geen akoestische modelvalidatie

| Materiaal | Onafhankelijke reference? | Gebruik |
|---|---|---|
| `140_Cm_Piano_VKeys_02_268_2.wav` | nee; akoestische herkomst onbevestigd | bestaande diagnostiek; eerder 15 ByteDance/27 Basic Pitch, geen TP/FP/FN |
| `120_G_Offbeat_01_53_SP.wav` | nee; akoestische herkomst onbevestigd | bestaande diagnostiek, geen accuracyclaims |
| UUID-bestanden onder uploads, waaronder één MP3 | geen gedocumenteerde gelijktijdige reference gevonden | onvoldoende herkomst/labels voor scoring |
| Baseline/holdout MIDI+WAV en stemfiles | ja, maar synthetisch gerenderd | bestaande synthetische benchmark, geen akoestisch bewijs |
| `transcription.mid` / `corrected-rN.mid` en testoutputs | prediction/correctie/demo | nooit onafhankelijke ground truth |

De zoekscope was het project inclusief uploads/artifacts/benchmarkdata en de
bekende project-/Codex-outputlocaties, geen volledige inventarisatie van alle
schijven. In de aanvullende zoekactie waren sommige tool/dependencydirectories
niet leesbaar; er is geen ontbrekende performance als bestaande opname aangenomen.

Scored acoustic set: **0 geschikte cases**. Nieuwe ByteDance- en Basic Pitch-
metrics, akoestische offset-/sustainconclusies en noisegevoeligheid: **niet gemeten**.
De oude ongelabelde resultaten worden niet opgewaardeerd tot kwaliteitsbewijs.
Er zijn in deze stap geen zware modelruns gedaan, policies toegepast of eerdere
benchmarkresultaten herschreven. Op dit moment blijft de engineconclusie
**MORE VALIDATION NEEDED**.

Stop na het aanleveren van de takes: daarna beoordelen we eerst herkomst,
reference en alignment. Pas geschikte echte gelabelde audio kan READY of READY
WITH KNOWN OFFSET LIMITATION ondersteunen, of aanleiding geven tot ENGINE
DECISION REOPEN. Dit document implementeert geen automatische import of modelrun.
