import argparse, platform, shutil, subprocess, sys, time
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


def cmd_report(a):
    """Verzamelt alles wat Claude nodig heeft in één tekst en kopieert die naar het klembord (macOS)."""
    d = job_paths(a.job)
    cfg = load_cfg(d)
    ver = run(["ffmpeg", "-version"], check=False).stdout.splitlines()[:1]
    parts = [f"REEL-EDITOR RAPPORT job={a.job}", f"ffmpeg: {ver[0] if ver else '?'}", f"platform: {platform.platform()}"]

    def add(title, p, limit=6000):
        p = d / p
        parts.append(f"\n--- {title} ---")
        parts.append(p.read_text(encoding="utf-8")[:limit] if p.exists() else "(ontbreekt)")

    add("timings.json", "timings.json")
    add("config.json (jouw instellingen)", "config.json")
    add("transcript.txt", "transcript.txt")
    cuts = load_json(d / "cuts.json")["cuts"] if (d / "cuts.json").exists() else []
    parts.append("\n--- knipplan ---")
    parts += [f"{c['kind']:8} {c['start']:7.2f}-{c['end']:7.2f} {'aan ' if c.get('enabled', True) else 'UIT '}{c['reason']}" for c in cuts] or ["(geen)"]
    add("verify.txt", "verify.txt")
    text = "\n".join(parts) + "\n"
    (d / "report.txt").write_text(text, encoding="utf-8")
    if shutil.which("pbcopy"):
        subprocess.run(["pbcopy"], input=text.encode("utf-8"))
        print(f"Rapport gekopieerd naar je klembord ({len(text)} tekens). Plak het in je gesprek met Claude (Cmd+V).")
    else:
        print(f"Rapport opgeslagen in {d / 'report.txt'} (geen pbcopy gevonden).")


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return "q"


def cmd_go(a):
    """Eén commando: transcriberen -> review -> (spelling/titel/CTA aanpassen) -> goedkeuren -> renderen -> controle."""
    src = Path(a.video).expanduser().resolve()
    name = a.name or src.stem
    d = JOBS / name
    have = (d / "transcript.raw.json").exists() and (d / "job.json").exists() and not a.again
    if have:
        print(f"Bestaande transcriptie van '{name}' hergebruikt (--again om opnieuw te transcriberen).")
        save_json(d / "job.json", {"source": str(src)})
        if not (d / "audio.wav").exists():
            tr.extract_audio(src, d / "audio.wav")
        cmd_plan(argparse.Namespace(job=name))
    else:
        cmd_transcribe(argparse.Namespace(video=str(src), name=name, model=None))

    def setcfg(**kv):
        c = load_json(d / "config.json")
        c.update(kv)
        save_json(d / "config.json", c)

    if a.title is not None:
        setcfg(title=a.title)
    if a.cta is not None:
        setcfg(cta=a.cta)
    while True:
        cmd_review(argparse.Namespace(job=name))
        cfgnow = load_cfg(d)
        print(f"\nTitel: {cfgnow['title'] or '(geen)'} · CTA: {cfgnow['cta'] or '(geen)'} · Captions: {cfgnow['caption_mode']}")
        ans = ask("\n[Enter] goedkeuren en renderen · f = spelling fixen · t = titel · c = CTA · m = captionmodus · q = stoppen\n> ")
        if ans == "":
            break
        if ans == "q":
            print("Gestopt. Hervat later met dezelfde opdracht (transcriptie wordt hergebruikt).")
            return
        if ans == "f":
            w, r = ask("Fout geschreven als: "), ask("Moet zijn: ")
            if w and r:
                cmd_fix(argparse.Namespace(job=name, wrong=w, right=r))
        elif ans == "t":
            setcfg(title=ask("Titel (leeg = geen): "))
        elif ans == "c":
            setcfg(cta=ask("CTA (leeg = geen): "))
        elif ans == "m":
            m = ask("none / sentence / word: ")
            if m in ("none", "sentence", "word"):
                setcfg(caption_mode=m)
    cmd_approve(argparse.Namespace(job=name))
    cmd_render(argparse.Namespace(job=name, yes=False))
    try:
        cmd_verify(argparse.Namespace(job=name, deep=a.deep))
    except SystemExit:
        print("Let op: controle meldde een FAIL, zie hierboven.")
    cmd_report(argparse.Namespace(job=name))
    out = load_json(d / "render_info.json")["out"]
    if shutil.which("open"):
        subprocess.run(["open", out])


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
    x = s.add_parser("report"); x.add_argument("job"); x.set_defaults(f=cmd_report)
    x = s.add_parser("go", help="alles in één keer, met vragen onderweg")
    x.add_argument("video"); x.add_argument("--name"); x.add_argument("--title"); x.add_argument("--cta")
    x.add_argument("--again", action="store_true", help="transcribeer opnieuw"); x.add_argument("--deep", action="store_true")
    x.set_defaults(f=cmd_go)
    a = p.parse_args()
    a.f(a)
