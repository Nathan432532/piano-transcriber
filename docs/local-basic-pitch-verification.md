# Lokale Basic Pitch-verificatie

Datum: 2026-10-05. Scope: uitsluitend de bestaande echte end-to-end-keten
reproduceerbaar starten en bewijzen. Geen applicatiebugs, editorfeatures,
transcriptieparameters of engines gewijzigd; geen commit gemaakt.

## Runtime en model

- Windows x64, officiële CPython 3.11.9 NuGet-distributie.
- Interpreter in gitignored `backend/.deps/python311`; virtualenv `.venv`.
- Basic Pitch 0.4.0, TensorFlow / tensorflow-intel 2.15.0, NumPy 1.26.4.
- Numba 0.59.1, llvmlite 0.42.0, resampy 0.4.2, setuptools 80.10.2.
- Exacte dependencies: `backend/requirements-windows.lock.txt`; `pip check` geslaagd.
- Expliciete runner `basic-pitch`, auto-run `1`, data-map `backend/data`.
- Package-model `basic_pitch/saved_models/icassp_2022/nmp`, daadwerkelijk geladen
  als `MODEL_TYPES.TENSORFLOW`.
- SHA-256 `saved_model.pb`:
  `eaa25c91c431c91100c416a2c018663f4c635f28fa19529c4ff5e14c18aa29c9`.
- Inferentie gebruikte de bestaande adapter met onset 0.70 / frame 0.40.

Basic Pitch's officiële metadata vereist hier TensorFlow `<2.15.1` voor
Python >=3.11. Daarom wordt de geteste Python 3.11-runtime expliciet gekozen.
Bron: https://github.com/spotify/basic-pitch/blob/v0.4.0/pyproject.toml

Windows Application Control blokkeerde `select.pyd` van de aanvankelijk geteste
python-build-standalone-runtime. De officiële Python-distributie werkte wel.
Een standaard MSI-installatie mislukte op een onbereikbaar cachebestand; de
installatievrije NuGet-distributie vermijdt die installatieroute. De automatisch
gekozen Numba 0.68.0 werd ook geblokkeerd; de geteste compatibele 0.59.1 werkte.
Nieuwste rpds-py werd vervangen door 0.22.3 voor de schematests. Er zijn geen
Windows-beveiligingsinstellingen gewijzigd of beveiligingsblokkades uitgeschakeld.

## Audio en uitgevoerde browserproef

Bij aanvang bevatte de checkout alleen synthetische `backend/data/samples/demo.wav`.
Die technische proef slaagde met echte inferentie (8 modelnoten).
Tijdens het werk verschenen twee WAVs in de repositoryroot. Deze bestanden
zijn niet gewijzigd of aan Git toegevoegd. De kortste pianoaudio is vervolgens
gebruikt voor de volledige browserproef:

- Bestand: `140_Cm_Piano_VKeys_02_268_2.wav`.
- Stereo, 24-bit PCM, 44100 Hz, 3.432131519 s.
- SHA-256: `66ff0c8706d151f8980a633a3563a8671131f1b05e9199bec650495fba9686d7`.
- Dit is lokaal testmateriaal; er is geen ground-truth/kwaliteitsbenchmark gedaan.
- Job: `12ad5149-7f41-44a4-9965-03906b087cd0`.
- Jobrecord: started `09:38:03Z`, finished `09:38:10Z` (11:38 lokale tijd).
- Modeloutput: 27 noten. De server logde `Predicting MIDI for ...wav...`.

De proef gebruikte de bestaande React-interface in de browser:

1. Upload via de uploadknop: HTTP 200.
2. Jobcreatie: HTTP 202; werkelijke inferentie via het TensorFlow-model.
3. `Succeeded`, original JSON/MIDI-links zichtbaar; `transcript.json` geladen.
4. Eerste noot via `Edit` aangepast: pitch 53 naar 54 en start van
   0.011609977324263039 naar 0.03 s; eindtijd 1.4512471655328798 s bleef behouden.
5. `Save` en `Save Corrections`: revisie 1, corrected JSON/MIDI-links zichtbaar.
6. Echte browserrefresh: dezelfde job, revisie en gewijzigde noot weer zichtbaar.
7. Nieuwe API-client: revisie/artifacts opnieuw opgehaald en MIDI inhoudelijk geparseerd.

Alle 27 MIDI-noten matchen corrected JSON: pitch en velocity exact; start/einde
binnen één tick (1/960 seconde). Originele artifacts blijven byte-identiek.
Corrected MIDI SHA-256:
`9afa5abe7035338c7726e2fc03c2f2d275758593fd7d1a7bd98f304aefd7c48b`.

De controle is uitgevoerd met:

```powershell
& .\.venv\Scripts\python.exe backend/scripts/verify_real_pipeline.py --job-id 12ad5149-7f41-44a4-9965-03906b087cd0
```

Daarnaast is het script zelf volledig uitgevoerd met de synthetische audio:
job `32e061e3-7ddd-40c4-b2b6-6b40d8bba61b`, 8 noten, correctie 60 naar 61,
revisie 1, alle MIDI/JSON-controles geslaagd. Het script simuleert een nieuwe
API-client; browserrefresh is afzonderlijk werkelijk uitgevoerd zoals hierboven.

## Tests en bestaande problemen

- Backend volledige suite: **100 passed, 2 failed**.
- `test_rejects_oversized_upload`: bestaande Windows bestandslockfout bij het
  verwijderen van een nog open temporary upload. Kleine uploads blokkeren hierdoor niet.
- `test_concurrent_idempotent_creates_return_one_job`: herhaald gefaald in deze
  Python 3.11-runtime met `400 Invalid upload path` tijdens gelijktijdige TestClient
  startup, in `ensure_child_path` / `ensure_job_dirs`. De enkele echte API-server
  en de uitgevoerde jobs slaagden. Geen oorzaakfix of concurrencygarantie geclaimd.
- Beide schematests slagen in de vastgezette runtime.
- Frontend: alle vier testbestanden, typecheck en production build geslaagd.
- Bekende lint-/canonical-duration-/demo-label-/cancel-/editorbeperkingen zijn
  ongewijzigd. Bij de korte opname toonde de bestaande UI na refresh nog 8 s;
  opgeslagen audio- en MIDI-timing zijn wel inhoudelijk gecontroleerd.
- Geen MP3-proef of vergelijking met ByteDance uitgevoerd.

Voor starten en opnieuw testen: volg de Windows-sectie in README.md. Jobs en
artifacts blijven lokaal onder `backend/data`; tijdelijke testuitvoer en
browserbewijs bevinden zich buiten de repository. Modelgewichten, interpreter,
virtualenv, node_modules en uploads zijn niet aan Git toegevoegd.
