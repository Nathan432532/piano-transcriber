import json
from pathlib import Path

import pytest

from benchmarks.maps.dataset import MANIFEST, check_txt, pair_audio, select, txt_reference
from benchmarks.maps.scoring import evaluate, match_rows, onset_window, policy_change


def note(pitch=60,start=.5,end=2.,sustain=None):
    return {"pitch":pitch,"startTime":start,"endTime":end,"sustainEndTime":end if sustain is None else sustain,"velocity":80}


def test_pairing_requires_identical_official_stems(tmp_path):
    stem=tmp_path/"MAPS_ISOL_NO_M_S0_M60_ENSTDkCl"
    for suffix in (".wav",".mid",".txt"):
        stem.with_suffix(suffix).write_bytes(b"fixture")
    assert pair_audio(tmp_path)==[(stem.with_suffix(".wav"),stem.with_suffix(".mid"),stem.with_suffix(".txt"))]
    stem.with_suffix(".mid").unlink()
    with pytest.raises(ValueError,match="Incomplete"):
        pair_audio(tmp_path)


def test_pairing_rejects_another_maps_instrument(tmp_path):
    stem=tmp_path/"MAPS_ISOL_NO_M_S0_M60_AkPnBcht"
    for suffix in (".wav",".mid",".txt"):
        stem.with_suffix(suffix).write_bytes(b"fixture")
    with pytest.raises(ValueError,match="instrument"):
        pair_audio(tmp_path)


def test_txt_tie_rounding_does_not_falsely_mismatch_chord_pitches(tmp_path):
    path=tmp_path/"official.txt"
    path.write_text("OnsetTime OffsetTime MidiPitch\n1.0000 2.0 67\n1.0000 2.0 60\n")
    refs=[note(67,1.000041,2),note(60,1.000039,2)]
    agreement=check_txt(refs,txt_reference(path))
    assert agreement["maxOnsetDifference"]==pytest.approx(.000041)
    assert agreement["maxEffectiveOffsetDifference"]==0


def test_txt_sustain_offset_is_not_physical_key_release(tmp_path):
    path=tmp_path/"official.txt"
    path.write_text("OnsetTime OffsetTime MidiPitch\n0.5 3.0 60\n")
    assert check_txt([note(end=1,sustain=3)],txt_reference(path))["maxEffectiveOffsetDifference"]==0


def record(name,source,style,pitches,duration=2,pedal=False):
    notes=[note(p,start=.5,end=.5+duration,sustain=.5+duration+.3 if pedal else None) for p in pitches]
    return {"audio":name,"mapsCategory":source,"style":style,"notes":notes,"pedalDownRecorded":pedal,
            "sustain":pedal,"duration":max(15.,duration+2),"maxNoteDuration":duration,"pitchRange":[min(pitches),max(pitches)]}


def pool():
    values=[record(f"ISOL/NO/{p}.wav","ISOL","NO",[p]) for p in (36,60,84,100)]
    values += [record(f"ISOL/LG/{d}.wav","ISOL","LG",[60],d) for d in (3.5,5.5,8,12,18)]
    values += [record(f"ISOL/RE/{p}.wav","ISOL","RE",[p]*4) for p in (48,67,90)]
    values += [record(f"ISOL/NO/S1_{p}.wav","ISOL","NO",[p],pedal=True) for p in (48,67,90)]
    values += [record("UCHO/a.wav","UCHO",None,[48,62]),record("UCHO/b.wav","UCHO",None,[60,67,74]),
               record("RAND/a.wav","RAND",None,[48,62]),record("RAND/b.wav","RAND",None,[60,70,80])]
    values += [record(f"MUS/{i}.wav","MUS",None,[60,64,67]) for i in range(6)]
    return values


def test_selection_is_model_free_deterministic_and_covers_24_cases():
    forward=select(pool())
    assert forward==select(list(reversed(pool())))
    assert len({r["audio"] for r,_,_ in forward})==24
    counts={category:sum(c==category for _,c,_ in forward) for category in {c for _,c,_ in forward}}
    assert counts=={"isolated":4,"long":5,"repeated":3,"sustain":3,"chords":4,"music":5}
    assert [r["audio"] for r,c,_ in forward if c=="music"]==[f"MUS/{i}.wav" for i in range(5)]


def test_selection_never_infers_sustain_from_filename_alone():
    values=[r for r in pool() if not r["pedalDownRecorded"]]
    values.append(record("ISOL/NO/looks_S1.wav","ISOL","NO",[48],pedal=False))
    with pytest.raises(ValueError,match="sustain"):
        select(values)


def test_frozen_manifest_parses_without_any_dataset_or_models():
    manifest=json.loads(MANIFEST.read_text())
    assert manifest["zipFilename"]=="ENSTDkCl.zip" and manifest["zipBytes"]==2608287080
    assert manifest["zipMd5"]=="72bbdf40eb7af69225755e165a0a0a08"
    assert len(manifest["cases"])==len({c["caseId"] for c in manifest["cases"]})==24
    assert manifest["alignmentOffsetSeconds"]==0
    assert all(not Path(c["audio"]).is_absolute() for c in manifest["cases"])


def test_crop_selects_same_onset_window_without_clipping_note_ends():
    notes=[note(start=.5,end=12),note(start=10,end=11),note(start=11,end=12)]
    selected=onset_window(notes,[0,10])
    assert selected==[notes[0]] and selected[0]["endTime"]==12


def test_offset_analysis_remains_separate_from_primary_matching():
    refs=[note(end=2,sustain=3)]
    predictions=[note(end=2)]
    result=evaluate(refs,predictions,4)
    assert (result["TP"],result["FP"],result["FN"])==(1,0,0)
    assert result["offset_mae_ms"]==0 and result["sustain_offset_mae_ms"]==1000
    assert result["effective_early"]==1


def test_censored_offsets_are_flagged_without_dropping_onset_matches():
    result=evaluate([note(end=4)],[note(end=2)],3)
    assert result["TP"]==1 and result["key_censored_matches"]==1
    assert result["offset_mae_ms"] is None and result["offset_max_abs_ms"] is None


def test_note_csv_keeps_false_positive_and_false_negative_separate():
    refs=[note(60),note(64,start=1)]
    predictions=[note(60),note(65,start=1)]
    result=evaluate(refs,predictions,3)
    rows=match_rows(refs,predictions,result,3)
    assert sorted(r["match"] for r in rows)==["FN","FP","TP"]
    assert (result["TP"],result["FP"],result["FN"])==(1,1,1)


def test_policy_comparison_detects_correct_long_note_cut_early():
    outcome=policy_change(5,4,note(end=5))
    assert outcome["newEarly"] and outcome["correctKeyCutEarly"] and outcome["keyWorsened"]


def test_policy_comparison_does_not_hide_sustain_regression_by_key_improvement():
    outcome=policy_change(6,2,note(end=2,sustain=6))
    assert outcome["keyImproved"] and outcome["effectiveWorsened"] and outcome["sustainMovedEarlierAndWorsened"]


def test_common_error_comparison_uses_same_gt_identities_not_engine_coverage():
    from benchmarks.maps.report import common_matches
    def row(engine,case,index,error,match="TP"):
        return {"engine":engine,"case":case,"referenceIndex":index,"match":match,
                "onset_error":.01,"key_error":error,"pedal_error":error}
    rows=[row("bytedance","a",0,.1),row("basic_pitch","a",0,.2),
          row("bytedance","a",1,10),row("basic_pitch","a",1,None,"FN"),
          row("basic_pitch","b",0,20)]
    result=common_matches(rows)
    assert result["bytedance"]["matched"]==result["basic_pitch"]["matched"]==1
    assert result["bytedance"]["key_error"]["mae_ms"]==100
    assert result["basic_pitch"]["key_error"]["mae_ms"]==200


def test_annotation_audit_flags_pedal_event_order_outside_frozen_window(tmp_path):
    import mido
    from benchmarks.maps.report import annotation_audit
    stem=tmp_path/"MAPS_MUS-fixture_ENSTDkCl"
    stem.with_suffix(".wav").touch()
    midi=mido.MidiFile(ticks_per_beat=1000)
    midi.tracks.append(mido.MidiTrack([
        mido.Message("note_on",note=60,velocity=80,time=4000),
        mido.Message("note_off",note=60,time=2000),
        mido.Message("control_change",control=64,value=127,time=0),
        mido.Message("control_change",control=64,value=0,time=2000)]))
    midi.save(stem.with_suffix(".mid"))
    stem.with_suffix(".txt").write_text("OnsetTime OffsetTime MidiPitch\n2 4 60\n")
    manifest={"cases":[{"audio":stem.name+".wav","evaluationOnsetWindowSeconds":[0,1]}]}
    result=annotation_audit(tmp_path,manifest)
    assert result["selectedEffectiveDifferencesOver1ms"]==[]
    exception=result["fullDatasetEffectiveDifferencesOver1ms"][0]
    assert exception["effectiveRelease"]==3 and exception["txtRelease"]==4
    assert exception["pedalDownAtSameTimestampAsKeyRelease"] is True
