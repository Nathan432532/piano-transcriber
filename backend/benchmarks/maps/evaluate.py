"""Offline MAPS scoring/traces, reusing the original benchmark matcher and B."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import importlib.metadata
import inspect
import json
from pathlib import Path
import statistics
import zipfile

import numpy as np
import soundfile as sf

from benchmarks.metrics import aggregate, read_midi
from benchmarks.offset_helpers import decoder_trace
from benchmarks.prepare import ROOT, sha256
from benchmarks.experiments.offset_policy.policies import evaluate_event
from .dataset import MANIFEST, resolve_root, verify, inspect as inspect_dataset
from .infer import audio_for_case
from .scoring import evaluate, match_rows, onset_window, policy_change

HERE=Path(__file__).parent
POLICY=ROOT/"backend/benchmarks/experiments/offset_policy/policies.py"
POLICY_SHA="f6e1d8b8a311e0e23b2c84f9451b1aa91cf50758dafd267b45dca55e2446814e"


def read_json(path):
    return json.loads(path.read_text())


def validated_cache(engine,case,root,output):
    directory=output/"predictions"/engine/case["caseId"]
    meta=read_json(directory/"provenance.json")
    audio=audio_for_case(root,case,output)
    if meta["identity"]["audioSha256"]!=sha256(audio) or meta["sourceAudioSha256"]!=case["audioSha256"]:
        raise ValueError("Cache audio provenance differs")
    for package,version in meta["identity"]["versions"].items():
        if importlib.metadata.version(package)!=version:
            raise ValueError("Cache engine/dependency version differs")
    if meta["identity"]["adapterAndDecoderSha256"][engine+"_adapter.py"]!=sha256(ROOT/f"backend/app/{engine}_adapter.py"):
        raise ValueError("Cache adapter differs")
    if meta["identity"]["adapterAndDecoderSha256"]["transcription_jobs.py"]!=sha256(ROOT/"backend/app/transcription_jobs.py"):
        raise ValueError("Canonical validator differs")
    weights=ROOT/"backend/data/models" if engine=="bytedance" else ROOT/".venv/Lib/site-packages/basic_pitch/saved_models/icassp_2022/nmp"
    for name,digest in meta["identity"]["modelFilesSha256"].items():
        if sha256(weights/name)!=digest:
            raise ValueError("Cached engine model differs")
    for name,digest in meta["artifactSha256"].items():
        if sha256(directory/name)!=digest:
            raise ValueError("Cached artifact changed")
    return read_json(directory/"transcript.json"),meta,audio


def b_and_traces(case,transcript,output):
    assert sha256(POLICY)==POLICY_SHA,"Policy B must remain unchanged"
    directory=output/"predictions/bytedance"/case["caseId"]
    events=read_json(directory/"library-events.json")
    duration=transcript["source"]["duration"]
    with np.load(directory/"library-framewise-output.npz") as source:
        matrices={key:source[key] for key in source.files}
    from piano_transcription_inference.piano_vad import note_detection_with_onset_offset_regress
    cached_meta=read_json(directory/"provenance.json")
    from piano_transcription_inference import inference,utilities,piano_vad,models
    for module in (inference,utilities,piano_vad,models):
        path=Path(inspect.getfile(module))
        assert sha256(path)==cached_meta["identity"]["adapterAndDecoderSha256"][path.name]
    notes=transcript["notes"]
    library_events=sorted([e for e in events["notes"] if e["onset_time"]<duration],key=lambda e:(e["onset_time"],e["midi_note"],min(e["offset_time"],duration)))
    assert len(library_events)==len(notes)
    traces={}
    for pitch in {n["pitch"] for n in notes}:
        column=pitch-21
        args=[matrices[key][:,column] for key in ("frame_output","onset_output","onset_shift_output","offset_output","offset_shift_output","velocity_output")]+[.1]
        explained=decoder_trace(*args)
        original=note_detection_with_onset_offset_regress(*args)
        assert len(explained)==len(original)
        for trace,tuple_ in zip(explained,original):
            assert [trace[k] for k in ("beginFrame","endFrame","onsetShift","offsetShift","velocityRaw")]==[float(x) for x in tuple_]
        traces[pitch]=explained
    b_notes,details=[],[]
    for index,(note,event) in enumerate(zip(notes,library_events)):
        trace=min(traces[note["pitch"]],key=lambda t:abs(t["onsetSeconds"]-note["startTime"]))
        assert abs(trace["offsetSeconds"]-event["offset_time"])<1e-6
        assert abs(trace["onsetSeconds"]-note["startTime"])<1e-6
        following=[n["startTime"] for n in notes if n["pitch"]==note["pitch"] and n["startTime"]>note["startTime"]]
        # Only B is consumed. No silence bound, C/D scoring or production policy.
        candidate=evaluate_event(event,trace,matrices,duration,events["pedal"] or [],min(following,default=None),None)
        assert candidate["A"]==note["endTime"]
        b_notes.append({**note,"endTime":candidate["B"]})
        column=note["pitch"]-21
        peaks=[{"frame":int(i),"time":(int(i)+float(matrices["offset_shift_output"][i,column]))/100,
                "score":float(matrices["reg_offset_output"][i,column])} for i in np.flatnonzero(matrices["offset_output"][:,column])
               if i>trace["beginFrame"] and i/100<=min(duration,min(following,default=float("inf"))) ]
        details.append({"predictionIndex":index,"pitch":note["pitch"],"onset":note["startTime"],"upstreamOffset":event["offset_time"],
                        "canonicalOffset":note["endTime"],"policyBOffset":candidate["B"],"policyBReason":candidate["reason_B"],
                        "rawCandidate":candidate["raw_candidate_offset"],"offsetPeaks":peaks,"decoder":trace,
                        "audioDuration":duration,"outputFrames":len(matrices["frame_output"]),"realAudioFrameLimit":int(duration*100),
                        "predictedPedalEvents":events["pedal"],"clippingApplied":event["offset_time"]>duration})
    assert [(n["pitch"],n["startTime"]) for n in notes]==[(n["pitch"],n["startTime"]) for n in b_notes]
    return b_notes,details


def extended_aggregate(results,rows):
    total=aggregate(results)
    for field in ("offset_gt250ms","offset_gt500ms","offset_gt1s","offset_early","offset_late","effective_early","effective_late","audio_end_exact","audio_end_near10ms","key_censored_matches","effective_censored_matches","changed_offsets","key_improved","key_worsened","effective_improved","effective_worsened","new_early","correct_key_cut_early","sustain_regression"):
        total[field]=sum(r.get(field,0) for r in results)
    for kind in ("onset","offset","sustain_offset"):
        total[kind+"_max_abs_ms"]=max((abs(x)*1000 for r in results for x in r["errors"][kind]),default=None)
    total["runtime_seconds"]=sum(r.get("runtime_seconds",0) for r in results)
    total["peak_rss_mib"]=max((r.get("peak_rss_mib",0) for r in results),default=None)
    return total


def run(root,output):
    root=resolve_root(root)
    output=output.resolve()
    manifest=read_json(MANIFEST)
    verify(root,manifest)
    case_results,notes_rows,all_traces,provenance,comparisons=[],[],[],{},[]
    for case in manifest["cases"]:
        reference=onset_window(read_midi(root/case["midi"]),case["evaluationOnsetWindowSeconds"])
        assert len(reference)==case["groundTruthNotes"]
        for engine in ("bytedance","basic_pitch"):
            transcript,meta,audio=validated_cache(engine,case,root,output)
            predictions=onset_window(transcript["notes"],case["evaluationOnsetWindowSeconds"])
            duration=transcript["source"]["duration"]
            result=evaluate(reference,predictions,duration)
            result.update(case=case["caseId"],category=case["category"],mapsCategory=case["mapsCategory"],engine=engine,
                          runtime_seconds=meta["runtimeSeconds"],peak_rss_mib=meta["peakRssMiB"],changed_offsets=0)
            case_results.append(result)
            rows=match_rows(reference,predictions,result,duration)
            for row in rows:
                row.update(case=case["caseId"],category=case["category"],engine=engine)
            notes_rows.extend(rows)
            provenance[case["caseId"]+"/"+engine]=meta
            if engine!="bytedance":
                continue
            b_full,traces=b_and_traces(case,transcript,output)
            b_predictions=onset_window(b_full,case["evaluationOnsetWindowSeconds"])
            b=evaluate(reference,b_predictions,duration)
            for field in ("TP","FP","FN","F1","onset_mae_ms"):
                assert result[field]==b[field],"Policy B changed pitch/onset outcomes"
            b.update(case=case["caseId"],category=case["category"],mapsCategory=case["mapsCategory"],engine="bytedance_B_offline",runtime_seconds=0,peak_rss_mib=0,
                     changed_offsets=sum(abs(a["endTime"]-n["endTime"])>1e-7 for a,n in zip(predictions,b_predictions)))
            matched=result["diagnostics"]["correct"]
            changes=[]
            for m in matched:
                i,j=m["referenceIndex"],m["predictionIndex"]
                change=policy_change(predictions[j]["endTime"],b_predictions[j]["endTime"],reference[i])
                changes.append(change)
                if change["changed"]:
                    comparisons.append({"case":case["caseId"],"category":case["category"],"pitch":reference[i]["pitch"],
                                        "gtOnset":reference[i]["startTime"],"keyRelease":reference[i]["endTime"],"pedalRelease":reference[i]["sustainEndTime"],
                                        "A":predictions[j]["endTime"],"B":b_predictions[j]["endTime"],**change})
            for field,source in (("key_improved","keyImproved"),("key_worsened","keyWorsened"),("effective_improved","effectiveImproved"),("effective_worsened","effectiveWorsened"),("new_early","newEarly"),("correct_key_cut_early","correctKeyCutEarly"),("sustain_regression","sustainMovedEarlierAndWorsened")):
                b[field]=sum(c[source] for c in changes)
            case_results.append(b)
            for row in match_rows(reference,b_predictions,b,duration):
                row.update(case=case["caseId"],category=case["category"],engine="bytedance_B_offline")
                notes_rows.append(row)
            # Attach reference only after runtime B/traces have been computed.
            for row in rows:
                if row["predictionIndex"] is None:
                    continue
                predicted=predictions[row["predictionIndex"]]
                detail=next(t for t in traces if t["pitch"]==predicted["pitch"] and t["onset"]==predicted["startTime"])
                classification="unknown"
                if row["key_error"] is not None:
                    classification="reasonable" if abs(row["key_error"])<=.05 else "early" if row["key_error"]<0 else "late"
                    if row["gt_pedal_release"]>row["gt_key_release"]+1e-9 and row["pedal_error"] is not None and abs(row["pedal_error"])<=.05:
                        classification="sustain_ambiguity"
                all_traces.append({"case":case["caseId"],"category":case["category"],"classification":classification,**row,**detail})
    groups={}
    for category in sorted({c["category"] for c in manifest["cases"]})+["TOTAL"]:
        groups[category]={}
        for engine in ("bytedance","basic_pitch","bytedance_B_offline"):
            selected=[r for r in case_results if r["engine"]==engine and (category=="TOTAL" or r["category"]==category)]
            groups[category][engine]=extended_aggregate(selected,notes_rows)
    # Follow-up annotation QC corrects ASCII simultaneous-onset ordering only;
    # frozen selected files, labels, windows and alignment are never changed.
    audit_path=output/"annotation-audit.json"
    if not audit_path.exists():
        records,errors=inspect_dataset(root)
        audit={"pairs":len(records)+len(errors),"validPerPitchAnnotationPairs":len(records),"errors":errors,
               "initialFrozenOrderFlags":manifest["inventory"]["pairErrors"],
               "maxOnsetTxtDifference":max((r["txtAgreement"]["maxOnsetDifference"] for r in records),default=0),
               "maxEffectiveOffsetTxtDifference":max((r["txtAgreement"]["maxEffectiveOffsetDifference"] for r in records),default=0)}
        audit_path.write_text(json.dumps(audit,indent=2))
    pre_roll={}
    for case in manifest["cases"]:
        with sf.SoundFile(root/case["audio"]) as source:
            samples=source.read(round(.2*source.samplerate),always_2d=True)
        rms=float(np.sqrt(np.mean(samples*samples)))
        pre_roll[case["caseId"]]={"rms":rms,"dbFS":float(20*np.log10(rms)) if rms>0 else None,"windowSeconds":[0,.2],
                                 "description":"Native pre-roll level, not a controlled clean/noise experiment"}
    summary={"createdAt":datetime.now(timezone.utc).isoformat(),"manifestSha256":sha256(MANIFEST),"policyBSha256":sha256(POLICY),
             "groups":groups,"cases":case_results,"notes":notes_rows,"traces":all_traces,"policyBChanges":comparisons,
             "manifest":manifest,"provenance":provenance,"annotationAudit":read_json(audit_path),"nativePreRoll":pre_roll}
    (output/"maps-enstdkcl-summary.json").write_text(json.dumps(summary,indent=2))
    fields=["case","category","mapsCategory","engine","ground_truth_notes","predicted_notes","TP","FP","FN","precision","recall","F1",
            "onset_mae_ms","onset_median_abs_ms","onset_max_abs_ms","offset_mae_ms","offset_median_abs_ms","offset_max_abs_ms",
            "sustain_offset_mae_ms","sustain_offset_median_abs_ms","sustain_offset_max_abs_ms","offset_gt250ms","offset_gt500ms","offset_gt1s",
            "offset_early","offset_late","audio_end_exact","audio_end_near10ms","key_censored_matches","effective_censored_matches",
            "changed_offsets","key_improved","key_worsened","effective_improved","effective_worsened","new_early","correct_key_cut_early","sustain_regression","runtime_seconds","peak_rss_mib"]
    with (HERE/"maps-enstdkcl-results.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fields,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(case_results)
        writer.writerows({"case":"TOTAL","category":category,"engine":engine,**metric} for category,engines in groups.items() for engine,metric in engines.items())
    fields=["case","category","engine","match","referenceIndex","predictionIndex","pitch","gt_onset","gt_key_release","gt_pedal_release","pred_onset","pred_end","onset_error","key_error","pedal_error"]
    with (HERE/"maps-enstdkcl-note-results.csv").open("w",newline="",encoding="utf-8") as stream:
        writer=csv.DictWriter(stream,fields,extrasaction="ignore")
        writer.writeheader()
        writer.writerows(notes_rows)
    (output/"maps-enstdkcl-traces.json").write_text(json.dumps(all_traces,indent=2))
    print(json.dumps(groups["TOTAL"],indent=2))
    return summary


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    run(args.dataset_root,args.output)
