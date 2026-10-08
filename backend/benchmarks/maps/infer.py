"""Capture unmodified production-adapter predictions; dataset/cache stay external."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.metadata
import inspect
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import numpy as np
import psutil
import soundfile as sf

from benchmarks.prepare import ROOT, sha256
from .dataset import MANIFEST, resolve_root, verify


def identity(engine, audio, model_path):
    packages = ["numpy", "librosa", "soundfile", "mir_eval"]
    modules = [ROOT / f"backend/app/{engine}_adapter.py", ROOT / "backend/app/transcription_jobs.py"]
    if engine == "bytedance":
        packages += ["piano-transcription-inference", "torch", "torchlibrosa"]
        from piano_transcription_inference import inference, utilities, piano_vad, models
        modules += [Path(inspect.getfile(m)) for m in (inference,utilities,piano_vad,models)]
        modules.append(ROOT / "backend/benchmarks/offset_diagnosis.py")
        settings={"onset":.3,"offset":.3,"frame":.1,"pedal_offset":.2,"device":"cpu"}
    else:
        packages += ["basic-pitch", "tensorflow"]
        settings={"onset":.7,"frame":.4,"otherPredictArguments":"unchanged package defaults","device":"cpu"}
    files = [model_path] if model_path.is_file() else sorted(p for p in model_path.rglob("*") if p.is_file())
    return {"engine":engine,"audioSha256":sha256(audio),"adapterAndDecoderSha256":{p.name:sha256(p) for p in modules},
            "versions":{p:importlib.metadata.version(p) for p in packages},
            "modelFilesSha256":{p.name if model_path.is_file() else p.relative_to(model_path).as_posix():sha256(p) for p in files},
            "settings":settings}


def audio_for_case(root, case, output):
    original=root/case["audio"]
    if case["category"] != "music":
        return original
    dest=output/"audio"/(case["caseId"]+".wav")
    dest.parent.mkdir(parents=True,exist_ok=True)
    start,end=case["audioWindowSeconds"]
    with sf.SoundFile(original) as source:
        source.seek(round(start*source.samplerate))
        samples=source.read(round((end-start)*source.samplerate),dtype="int16",always_2d=True)
        rate=source.samplerate
    if dest.exists():
        existing,saved_rate=sf.read(dest,dtype="int16",always_2d=True)
        if saved_rate!=rate or not np.array_equal(samples,existing):
            raise ValueError("Derived music audio differs from frozen original samples")
    else:
        sf.write(dest,samples,rate,subtype="PCM_16")
    return dest


def run(root, output, engine):
    root=resolve_root(root)
    output=output.resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("MAPS data and inference caches must stay outside repository")
    manifest=json.loads(MANIFEST.read_text())
    verify(root,manifest)
    # Models are loaded once per engine process, with production defaults.
    from app.transcription_jobs import validate_transcript_payload
    if engine == "bytedance":
        from app.bytedance_adapter import ByteDanceTranscriptionAdapter
        from benchmarks.offset_diagnosis import ObservingBinding
        path=ROOT/"backend/data/models/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth"
        binding=ObservingBinding()
        adapter=ByteDanceTranscriptionAdapter(path,binding)
    else:
        from app.basic_pitch_adapter import BasicPitchTranscriptionAdapter, resolve_basic_pitch_model_path
        path=resolve_basic_pitch_model_path(None)
        binding=None
        adapter=BasicPitchTranscriptionAdapter(path)
    loaded=False
    load_time=None
    process=psutil.Process()
    for case in manifest["cases"]:
        audio=audio_for_case(root,case,output)
        fingerprint=identity(engine,audio,path)
        dest=output/"predictions"/engine/case["caseId"]
        if (dest/"provenance.json").exists():
            saved=json.loads((dest/"provenance.json").read_text())
            if saved["identity"] != fingerprint:
                raise ValueError(f"Cache identity differs: {engine}/{case['caseId']}; keep old run and use new --output")
            for name,digest in saved["artifactSha256"].items():
                if sha256(dest/name)!=digest:
                    raise ValueError("Cached prediction/heads changed")
            print(f"CACHE {engine}/{case['caseId']}",flush=True)
            continue
        context=SimpleNamespace(upload_path=audio,job={"engine":engine})
        if not loaded:
            print(f"Loading real {engine} production adapter",flush=True)
            start=time.perf_counter()
            adapter.load(context)
            load_time=time.perf_counter()-start
            loaded=True
        if binding is not None:
            binding.segment_inputs.clear()
            binding.segment_outputs.clear()
        print(f"INFERENCE {engine}/{case['caseId']} ({sf.info(audio).duration:.3f}s audio)",flush=True)
        peak=[process.memory_info().rss]
        stop=threading.Event()
        def sample():
            while not stop.wait(.1):
                peak[0]=max(peak[0],process.memory_info().rss)
        watcher=threading.Thread(target=sample,daemon=True)
        watcher.start()
        start=time.perf_counter()
        try:
            result=adapter.transcribe(context,lambda *args:None)
            canonical=validate_transcript_payload(result["_transcript"])
        finally:
            stop.set()
            watcher.join()
        runtime=time.perf_counter()-start
        dest.mkdir(parents=True,exist_ok=True)
        (dest/"transcript.json").write_text(json.dumps(canonical,indent=2))
        if binding is not None:
            library=binding.library_output
            raw={key:np.concatenate([chunk[key] for chunk in binding.segment_outputs],axis=0) for key in binding.segment_outputs[0]}
            for key,values in raw.items():
                assert np.array_equal(binding._model.deframe(values.copy())[:round(binding.duration*16000)],library["output_dict"][key])
            np.savez_compressed(dest/"raw-segment-heads.npz",**raw)
            np.savez_compressed(dest/"library-framewise-output.npz",**library["output_dict"])
            (dest/"library-events.json").write_text(json.dumps({"notes":library["est_note_events"],"pedal":library["est_pedal_events"]},indent=2,default=float))
        metadata={"createdAt":datetime.now(timezone.utc).isoformat(),"manifestSha256":sha256(MANIFEST),
                  "identity":fingerprint,"sourceAudioSha256":case["audioSha256"],"runtimeSeconds":runtime,
                  "modelLoadSeconds":load_time,"peakRssMiB":peak[0]/1024**2,
                  "memoryMethod":"100ms process RSS samples; includes model/runtime; warm sequential engine process",
                  "audioDuration":sf.info(audio).duration,
                  "artifactSha256":{p.name:sha256(p) for p in dest.iterdir() if p.is_file()}}
        assert datetime.fromisoformat(metadata["createdAt"])>datetime.fromisoformat(manifest["frozenAt"])
        (dest/"provenance.json").write_text(json.dumps(metadata,indent=2))
        print(f"SAVED {len(canonical['notes'])} notes; {runtime:.3f}s; peak {metadata['peakRssMiB']:.1f}MiB",flush=True)
        load_time=0.
    if binding is not None and loaded:
        binding.hook.remove()


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--engine",required=True,choices=["bytedance","basic_pitch"])
    args=parser.parse_args()
    run(args.dataset_root,args.output,args.engine)
