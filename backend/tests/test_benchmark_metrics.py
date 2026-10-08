from pathlib import Path

import mido
import pytest

from benchmarks.metrics import read_midi, score, aggregate


def note(pitch=60, start=0.5, end=1.0, velocity=80):
    return dict(pitch=pitch, startTime=start, endTime=end, velocity=velocity, sustainEndTime=end)


def test_midi_seconds_follow_tempo_and_velocity_zero_note_off(tmp_path):
    path = tmp_path / "tempo.mid"
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.extend([mido.MetaMessage("set_tempo", tempo=500000),
                  mido.Message("note_on", note=60, velocity=80, time=480),
                  mido.MetaMessage("set_tempo", tempo=1000000, time=480),
                  mido.Message("note_on", note=60, velocity=0, time=480)])
    midi.save(path)
    assert read_midi(path) == [note(start=0.5, end=2.0)]


def test_midi_pedal_release_and_reattack_are_separate_from_key_release(tmp_path):
    path = tmp_path / "pedal.mid"
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.extend([mido.Message("control_change", control=64, value=127),
                  mido.Message("note_on", note=60, velocity=80, time=480),
                  mido.Message("note_off", note=60, time=240),
                  mido.Message("note_on", note=60, velocity=80, time=240),
                  mido.Message("note_off", note=60, time=240),
                  mido.Message("control_change", control=64, value=0, time=240)])
    midi.save(path)
    first, second = read_midi(path)
    assert first["endTime"] == .75 and first["sustainEndTime"] == 1
    assert second["endTime"] == 1.25 and second["sustainEndTime"] == 1.5


@pytest.mark.parametrize("error,tp", [(0.05, 1), (0.0501, 0), (-0.05, 1)])
def test_onset_boundary_is_inclusive(error, tp):
    result = score([note()], [note(start=.5 + error)])
    assert result["TP"] == tp


def test_duplicate_onset_cannot_match_reference_twice():
    result = score([note()], [note(), note(start=.51)])
    assert (result["TP"], result["FP"], result["FN"]) == (1, 1, 0)
    assert result["precision"] == .5 and result["recall"] == 1


def test_maximum_matching_avoids_greedy_loss():
    refs = [note(start=.5), note(start=.56, end=1.06)]
    preds = [note(start=.52), note(start=.46)]
    result = score(refs, preds)
    assert result["TP"] == 2


def test_right_pitch_wrong_timing_and_wrong_pitch_have_distinct_scores():
    delayed = score([note()], [note(start=.7)])
    assert delayed["pitch_F1"] == 1 and delayed["onset_F1"] == 0 and delayed["F1"] == 0
    assert len(delayed["diagnostics"]["right_pitch_wrong_timing"]) == 1
    wrong = score([note()], [note(pitch=61)])
    assert wrong["pitch_F1"] == 0 and wrong["onset_F1"] == 1 and wrong["F1"] == 0
    assert len(wrong["diagnostics"]["wrong_pitch"]) == 1


def test_offsets_do_not_change_primary_note_score_and_cc64_is_separate():
    ref = note()
    ref["sustainEndTime"] = 1.5
    result = score([ref], [note(end=1.5)], velocity_reliable=True)
    assert result["F1"] == 1 and result["offset_F1"] == 0
    assert result["offset_mae_ms"] == 500 and result["sustain_offset_mae_ms"] == 0
    assert result["velocity_mae"] == 0


def test_missing_and_extra_notes_empty_predictions():
    missing = score([note()], [])
    assert (missing["TP"], missing["FP"], missing["FN"]) == (0, 0, 1)
    assert missing["onset_mae_ms"] is None
    extra = score([], [note()])
    assert (extra["TP"], extra["FP"], extra["FN"]) == (0, 1, 0)


def test_microaggregation_weights_matches_not_clips():
    first = score([note()], [note(start=.52)])
    refs = [note(pitch=pitch) for pitch in [61, 62, 63]]
    second = score(refs, refs)
    result = aggregate([first, second])
    assert result["ground_truth_notes"] == 4 and result["TP"] == 4
    assert result["onset_mae_ms"] == pytest.approx(5)


def test_unclosed_midi_is_rejected(tmp_path):
    path = tmp_path / "bad.mid"
    midi = mido.MidiFile()
    midi.tracks.append(mido.MidiTrack([mido.Message("note_on", note=60, velocity=80)]))
    midi.save(path)
    with pytest.raises(ValueError, match="Unclosed"):
        read_midi(path)


@pytest.mark.parametrize("case", ["missing_audio", "altered_audio", "altered_midi"])
def test_frozen_fixture_can_regenerate_missing_audio_but_rejects_contamination(tmp_path, monkeypatch, case):
    import json
    from benchmarks import prepare as module
    root = tmp_path / "checkout"
    fixtures, audio = root / "fixtures", root / "audio"
    fixtures.mkdir(parents=True)
    audio.mkdir()
    renderer = root / "renderer.exe"
    renderer.write_bytes(b"test renderer identity; never executed")
    plan = {"duration": 2, "notes": [(60, .5, 1, 80)]}
    midi = fixtures / "tiny.mid"
    wav = audio / "tiny.wav"
    module.write_midi(midi, plan)
    wav.write_bytes(b"deterministic test render payload")
    manifest = {"rendererExeSha256": module.sha256(renderer), "fragments": [{
        "name": "tiny", "midi": "fixtures/tiny.mid", "audio": "audio/tiny.wav",
        "midiSha256": module.sha256(midi), "audioSha256": module.sha256(wav)}]}
    manifest_path = fixtures / "baseline-manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "FIXTURES", fixtures)
    monkeypatch.setattr(module, "AUDIO", audio)
    monkeypatch.setattr(module, "PLANS", {"tiny": plan})
    monkeypatch.setattr(module, "render_audio", lambda _renderer, _sf, _midi, target: target.write_bytes(b"deterministic test render payload"))
    before_manifest = manifest_path.read_bytes()
    if case == "missing_audio":
        wav.unlink()
        assert module.prepare(renderer) == manifest
        assert module.sha256(wav) == manifest["fragments"][0]["audioSha256"]
    else:
        target = wav if case == "altered_audio" else midi
        target.write_bytes(b"contaminated")
        with pytest.raises(RuntimeError, match="hash mismatch"):
            module.prepare(renderer)
        assert target.read_bytes() == b"contaminated"
    assert manifest_path.read_bytes() == before_manifest
