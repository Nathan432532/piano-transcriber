"""MAPS-specific analysis layered on the existing mir_eval benchmark scoring."""
from __future__ import annotations

import statistics

from benchmarks.metrics import score


def onset_window(notes, window):
    return [n for n in notes if window[0] <= n["startTime"] < window[1]]


def evaluate(reference, predictions, audio_duration):
    result=score(reference,predictions)
    matches=result["diagnostics"]["correct"]
    key=[m["prediction"]["endTime"]-m["reference"]["endTime"] for m in matches if m["reference"]["endTime"]<=audio_duration]
    effective=[m["prediction"]["endTime"]-m["reference"]["sustainEndTime"] for m in matches if m["reference"]["sustainEndTime"]<=audio_duration]
    onset=result["errors"]["onset"]
    def summaries(values,prefix):
        absolute=[abs(v)*1000 for v in values]
        return {prefix+"_mae_ms":statistics.mean(absolute) if absolute else None,
                prefix+"_median_abs_ms":statistics.median(absolute) if absolute else None,
                prefix+"_max_abs_ms":max(absolute,default=None)}
    result.update(summaries(key,"offset"))
    result.update(summaries(effective,"sustain_offset"))
    result.update(summaries(onset,"onset"))
    result.update(offset_gt250ms=sum(abs(v)>.25 for v in key),offset_gt500ms=sum(abs(v)>.5 for v in key),offset_gt1s=sum(abs(v)>1 for v in key),
                  offset_early=sum(v<-.05 for v in key),offset_late=sum(v>.05 for v in key),
                  effective_early=sum(v<-.05 for v in effective),effective_late=sum(v>.05 for v in effective),
                  audio_end_exact=sum(n["endTime"]==audio_duration for n in predictions),
                  audio_end_near10ms=sum(abs(n["endTime"]-audio_duration)<=.01 for n in predictions),
                  key_censored_matches=sum(m["reference"]["endTime"]>audio_duration for m in matches),
                  effective_censored_matches=sum(m["reference"]["sustainEndTime"]>audio_duration for m in matches))
    # Identical primary matching; timing errors exclude only right-censored
    # endpoints beyond a prespecified crop, not difficult or unmatched notes.
    result["errors"]["offset"]=key
    result["errors"]["sustain_offset"]=effective
    return result


def match_rows(reference,predictions,metrics,duration):
    rows=[]
    by_ref={m["referenceIndex"]:m["predictionIndex"] for m in metrics["diagnostics"]["correct"]}
    used=set(by_ref.values())
    for i,ref in enumerate(reference):
        j=by_ref.get(i)
        pred=None if j is None else predictions[j]
        row={"match":"TP" if pred is not None else "FN","referenceIndex":i,"predictionIndex":j,
             "pitch":ref["pitch"],"gt_onset":ref["startTime"],"gt_key_release":ref["endTime"],"gt_pedal_release":ref["sustainEndTime"],
             "pred_onset":None if pred is None else pred["startTime"],"pred_end":None if pred is None else pred["endTime"],
             "key_error":None,"pedal_error":None,"onset_error":None}
        if pred is not None:
            row["onset_error"]=pred["startTime"]-ref["startTime"]
            if ref["endTime"]<=duration:
                row["key_error"]=pred["endTime"]-ref["endTime"]
            if ref["sustainEndTime"]<=duration:
                row["pedal_error"]=pred["endTime"]-ref["sustainEndTime"]
        rows.append(row)
    for j,pred in enumerate(predictions):
        if j not in used:
            rows.append({"match":"FP","referenceIndex":None,"predictionIndex":j,"pitch":pred["pitch"],
                         "gt_onset":None,"gt_key_release":None,"gt_pedal_release":None,"pred_onset":pred["startTime"],"pred_end":pred["endTime"],
                         "key_error":None,"pedal_error":None,"onset_error":None})
    return rows


def policy_change(a,b,reference):
    """No offset average is allowed to hide new early/sustain regressions."""
    key=reference["endTime"]
    effective=reference["sustainEndTime"]
    return {"changed":abs(b-a)>1e-7,
            "keyImproved":abs(b-key)<abs(a-key)-1e-7,"keyWorsened":abs(b-key)>abs(a-key)+1e-7,
            "effectiveImproved":abs(b-effective)<abs(a-effective)-1e-7,"effectiveWorsened":abs(b-effective)>abs(a-effective)+1e-7,
            "newEarly":b<effective-.05 and a>=effective-.05,
            "correctKeyCutEarly":abs(a-key)<=.05 and b<key-.05,
            "sustainMovedEarlierAndWorsened":effective>key+1e-9 and b<a and abs(b-effective)>abs(a-effective)+.05}
