import argparse, shutil, sys, time
from pathlib import Path
from .util import ROOT, load_json, save_json, deep_merge, duration, sha, run
from . import transcribe as tr, cuts as cu, render as rd, verify as vf

JOBS = ROOT / "jobs"


def job_paths(name):
    d = JOBS / name
    if not d.exists():
        sys.exit(f"Job '{name}' bestaat niet. Start met: ./reel transcribe <video>")
    return d


def load_cfg(d):
    return deep_merge(load_json(ROOT / "config.default.json"), load_json(d / "config.json"))


def timing(d, key, seconds):
    p = d / "timings.json"
    t = load_json(p) if p.exists() else {}
    t[key] = round(seconds, 1)
    save_json(p, t)


def cmd_transcribe(a):
    src = Path(a.video).expanduser().resolve()
    if not src.exists():
        sys.exit(f"Niet gevonden: {src}")
    name = a.name or src.stem
    d = JOBS / name
    d.mkdir(parents=True, exist_ok=True)
    if not (d / "config.json").exists():
        save_json(d / "config.json", {"title": "", "cta": "", "caption_mode": "sentence",
                                      "keep_silence": False})
    save_json(d / "job.json", {"source": str(src)})
    cfg = load_cfg(d)
    t0 = time.time()
    tr.extract_audio(src, d / "audio.wav")
    raw = tr.transcribe(d / "audio.wav", cfg, a.model)
    save_json(d / "transcript.raw.json", raw)
    timing(d, f"transcriptie_{raw['model']}", time.time() - t0)
    print(f"Transcriptie klaar in {time.time() - t0:.0f}s, {len(raw['words'])} woorden.")
    cmd_plan(argparse.Namespace(job=name))


def cmd_plan(a):
    d = job_paths(a.job)
    cfg = load_cfg(d)
    src = load_json(d / "job.json")["source"]
    words = tr.load_words(d, cfg)
    cuts, total = cu.plan(d / "audio.wav", words, cfg, d / "cuts.json")
    (d / "transcript.txt").write_text(cu.describe(words, cuts) + "\n", encoding="utf-8")
    keep = cu.keep_segments(cuts, total)
    new = sum(e - s for s, e in keep)
    print(f"Knipplan: {len([c for c in cuts if c['enabled']])} cuts, {total:.1f}s -> {new:.1f}s.")
    print("Review: ./reel review", a.job)


def cmd_review(a):
    d = job_paths(a.job)
    print((d / "transcript.txt").read_text(encoding="utf-8"))
    print("\n⟦woord⟧ = wordt weggeknipt (stumble) · [~Xs weg] = stilte weggeknipt")
    print(f"Spelling fixen:  ./reel fix {a.job} 'fout' 'juist'   (of bewerk jobs/{a.job}/config.json)")
    print(f"Knippen bijsturen: jobs/{a.job}/cuts.json  (\"enabled\": false of eigen cut met kind \"manual\")")
    print(f"Akkoord:         ./reel approve {a.job}")


def cmd_fix(a):
    d = job_paths(a.job)
    c = load_json(d / "config.json")
    c.setdefault("spelling", {})[a.wrong] = a.right
    save_json(d / "config.json", c)
    cmd_plan(argparse.Namespace(job=a.job))


def state_hash(d, cfg):
    words = tr.load_words(d, cfg)
    return sha({"w": [(w["text"], w["start"], w["end"]) for w in words], "c": load_json(d / "cuts.json")})


def cmd_approve(a):
    d = job_paths(a.job)
    cfg = load_cfg(d)
    save_json(d / "approved.json", {"hash": state_hash(d, cfg)})
    print("Transcript + knipplan goedgekeurd. Nu: ./reel render", a.job)


def cmd_render(a):
    d = job_paths(a.job)
    cfg = load_cfg(d)
    ap = d / "approved.json"
    if not a.yes and (not ap.exists() or load_json(ap)["hash"] != state_hash(d, cfg)):
        sys.exit(f"Transcript/knipplan niet goedgekeurd (of gewijzigd sinds goedkeuring).\n"
                 f"Eerst: ./reel review {a.job} en ./reel approve {a.job}")
    src = load_json(d / "job.json")["source"]
    words = tr.load_words(d, cfg)
    cuts = load_json(d / "cuts.json")
    out_dir = Path(cfg["paths"]["output_dir"]).expanduser() if cfg["paths"]["output_dir"] else d / "out"
    out = out_dir / f"{a.job}.mp4"
    t0 = time.time()
    info = rd.render(d, src, words, cuts["cuts"], cuts["source_duration"], cfg, out)
    timing(d, "render", time.time() - t0)
    save_json(d / "render_info.json", {"expected_duration": info["expected_duration"],
                                       "events": info["events"], "out": str(out)})
    print(f"Gerenderd: {out}  ({info['expected_duration']:.1f}s, {time.time() - t0:.0f}s verwerkingstijd)")
    print(f"Controle: ./reel verify {a.job}   (publiceren doe je zelf)")


def cmd_verify(a):
    d = job_paths(a.job)
    cfg = load_cfg(d)
    info = load_json(d / "render_info.json")
    fn = (lambda p: tr.transcribe(p, cfg)) if a.deep else None
    t0 = time.time()
    res = vf.verify(d, info["out"], info, cfg, deep=a.deep, whisper_fn=fn)
    for l, n, m in res:
        print(f"[{l}] {n}: {m}")
    timing(d, "verify" + ("_diep" if a.deep else ""), time.time() - t0)
    if any(l == "FAIL" for l, _, _ in res):
        sys.exit(1)


def main():
    p = argparse.ArgumentParser(prog="reel")
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("transcribe"); x.add_argument("video"); x.add_argument("--name"); x.add_argument("--model")
    x.set_defaults(f=cmd_transcribe)
    for n, f in (("plan", cmd_plan), ("review", cmd_review), ("approve", cmd_approve)):
        x = s.add_parser(n); x.add_argument("job"); x.set_defaults(f=f)
    x = s.add_parser("fix"); x.add_argument("job"); x.add_argument("wrong"); x.add_argument("right"); x.set_defaults(f=cmd_fix)
    x = s.add_parser("render"); x.add_argument("job"); x.add_argument("--yes", action="store_true",
        help="sla goedkeuring over (alleen voor tests)"); x.set_defaults(f=cmd_render)
    x = s.add_parser("verify"); x.add_argument("job"); x.add_argument("--deep", action="store_true",
        help="transcribeer de uitvoer opnieuw en vergelijk captions met de audio (traag)"); x.set_defaults(f=cmd_verify)
    a = p.parse_args()
    a.f(a)
