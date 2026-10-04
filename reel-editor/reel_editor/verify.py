"""Eerlijke controle van het eindbestand. Geeft PASS/WARN/FAIL per check."""
import difflib, statistics
from pathlib import Path
from .util import run, probe, silence_intervals, norm, save_json

TOL = 0.25  # seconden afwijking toegestaan op lengte


def verify(job_dir, out_path, info, cfg, deep=False, whisper_fn=None):
    job_dir, out_path = Path(job_dir), Path(out_path)
    res = []

    def add(level, name, msg):
        res.append((level, name, msg))

    if not out_path.exists():
        return [("FAIL", "bestand", f"{out_path} bestaat niet")]
    p = probe(out_path)
    v = next((s for s in p["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in p["streams"] if s["codec_type"] == "audio"), None)
    dur = float(p["format"]["duration"])
    exp = info["expected_duration"]
    o = cfg["output"]
    add("PASS" if abs(dur - exp) <= TOL else "FAIL", "lengte",
        f"uitvoer {dur:.2f}s, verwacht {exp:.2f}s uit knipplan (tolerantie {TOL}s)")
    ok = v and (int(v["width"]), int(v["height"])) == (o["width"], o["height"])
    add("PASS" if ok else "FAIL", "formaat",
        f"{v['width']}x{v['height']} {v['codec_name']} / audio {a['codec_name'] if a else 'GEEN'}" if v else "geen video")
    if not a:
        add("FAIL", "audio", "geen audiospoor")
    dec = run(["ffmpeg", "-v", "error", "-i", str(out_path), "-f", "null", "-"], check=False)
    add("PASS" if dec.returncode == 0 and not dec.stderr.strip() else "FAIL", "afspeelbaar",
        "volledig gedecodeerd zonder fouten" if not dec.stderr.strip() else dec.stderr[:300])

    ev = info["events"]
    caps = [e for e in ev if e["kind"] == "caption"]
    cta = [e for e in ev if e["kind"] == "cta"]
    ttl = [e for e in ev if e["kind"] == "title"]
    add("PASS" if bool(cta) == bool(cfg.get("cta")) else "FAIL", "CTA",
        f"CTA '{cfg.get('cta')}' van {cta[0]['start']:.1f}s tot einde" if cta else "geen CTA (zoals ingesteld)")
    add("PASS" if bool(ttl) == bool(cfg.get("title")) else "FAIL", "titel",
        "titel aanwezig" if ttl else "geen titel (zoals ingesteld)")
    if cfg["caption_mode"] == "sentence":
        overl = sum(1 for x, y in zip(caps, caps[1:]) if y["start"] < x["end"] - 1e-6)
        add("PASS" if overl == 0 else "FAIL", "1 zin tegelijk", f"{overl} overlappende captions")
    if cfg["caption_mode"] == "word":
        multi = sum(1 for c in caps if len(c["text"].split()) > 1)
        add("PASS" if multi == 0 else "WARN", "1 woord tegelijk",
            f"{multi} captions met >1 woord (samengestelde termen uit spellinglijst tellen mee)")

    if caps:
        ass = (job_dir / "captions.ass").read_text(encoding="utf-8")
        multi = [l for l in ass.splitlines() if l.startswith("Dialogue") and ",Caption," in l and "\\N" in l]
        from .captions import caption_limit
        lim = caption_limit(cfg)
        too_long = [e["text"] for e in caps if len(e["text"]) > lim] if cfg["caption_mode"] == "sentence" else []
        add("PASS" if not multi and not too_long else "FAIL" if multi else "WARN", "captions op 1 regel",
            f"{len(multi)} met regelbreuk" + (f"; {len(too_long)} langer dan {lim} tekens (kan buiten beeld lopen): "
                                              f"{too_long[0][:40]}..." if too_long else ""))

    # captions tegen audio: staat er een caption terwijl het stil is?
    if caps:
        sil = [(s, e if e is not None else dur) for s, e in silence_intervals(out_path, cfg["silence"]["noise_db"], 0.3)]
        bad = []
        for c in caps:
            d = c["end"] - c["start"]
            inside = sum(max(0, min(c["end"], e) - max(c["start"], s)) for s, e in sil)
            if d > 0 and inside / d > 0.6:
                bad.append(c)
        add("PASS" if not bad else "WARN", "captions vs stilte (grof)",
            f"{len(bad)}/{len(caps)} captions staan grotendeels in stilte" +
            (": " + "; ".join(f"{b['start']:.1f}s '{b['text'][:25]}'" for b in bad[:5]) if bad else ""))
        if cfg["keep_silence"] is False:
            left = [(s, e) for s, e in sil if e - s > cfg["silence"]["min_gap"] + 0.3]
            add("PASS" if not left else "WARN", "resterende stiltes",
                f"{len(left)} stiltes langer dan {cfg['silence']['min_gap'] + 0.3:.1f}s over")

    if deep and caps and whisper_fn:
        spoken = [w for w in whisper_fn(out_path)["words"] if norm(w["text"])]
        s_tok = [norm(w["text"]) for w in spoken]
        c_tok, c_meta = [], []  # per captionwoord: (caption, is_eerste_woord)
        for c in caps:
            toks = [t for t in c["text"].split() if norm(t)]
            for k, t in enumerate(toks):
                c_tok.append(norm(t))
                c_meta.append((c, k == 0))
        sm = difflib.SequenceMatcher(None, s_tok, c_tok, autojunk=False)
        diffs = []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op != "equal":
                diffs.append(f"gesproken '{' '.join(s_tok[i1:i2])}' vs caption '{' '.join(c_tok[j1:j2])}'")
        add("PASS" if sm.ratio() > 0.9 else "WARN", "captiontekst vs gesproken tekst (diep)",
            f"{sm.ratio() * 100:.0f}% overeenkomst. Verschillen: " + ("; ".join(diffs[:8]) or "geen") +
            ". Let op: Whisper schrijft bij een tweede pass soms anders; dit is geen bewijs van fout in de caption.")
        # timing: caption moet verschijnen rond het eerste woord van de caption (zin- of woordmodus)
        starts = []
        for blk in sm.get_matching_blocks():
            for k in range(blk.size):
                c, first = c_meta[blk.b + k]
                if first:
                    starts.append((c["start"] - spoken[blk.a + k]["start"], c))
        if starts:
            offs = [o for o, _ in starts]
            worst = max(offs, key=abs)
            ok = abs(statistics.median(offs)) < 0.25 and abs(worst) < 0.5
            add("PASS" if ok else "WARN", "caption-start vs eerste woord (diep)",
                f"{len(starts)}/{len(caps)} captions gecontroleerd, mediaan {statistics.median(offs) * 1000:+.0f} ms, "
                f"slechtste {worst * 1000:+.0f} ms (negatief = caption eerder dan woord)")
        else:
            add("WARN", "caption-start vs eerste woord (diep)", "geen enkel eerste woord kon gematcht worden")
    elif deep:
        add("WARN", "diep", "geen Whisper beschikbaar")

    # frames om zelf te bekijken
    fdir = job_dir / "verify"
    fdir.mkdir(exist_ok=True)
    pts = [min(1.0, dur / 2)] + ([max(dur - 1.0, 0)] if cfg.get("cta") else [])
    for t in pts:
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(out_path),
             "-frames:v", "1", str(fdir / f"frame_{t:05.1f}s.png")], check=False)
    add("INFO", "frames", f"stilstaande beelden in {fdir}/ (kijk zelf: positie, leesbaarheid, afgesneden tekst)")
    add("INFO", "niet automatisch te controleren",
        "of titel boven je hoofd staat, of de stijl klopt, en of het sneden natuurlijk aanvoelen: dat beoordeel jij")
    report = "\n".join(f"[{l}] {n}: {m}" for l, n, m in res)
    (job_dir / "verify.txt").write_text(report + "\n", encoding="utf-8")
    return res
