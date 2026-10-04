"""Knipplan: stiltes + stumbles -> cuts.json -> keep-segmenten -> tijdlijn-remap.
cuts.json is voor Stijn bewerkbaar: zet "enabled": false of voeg handmatige cuts toe."""
from pathlib import Path
from .util import load_json, save_json, silence_intervals, duration, norm, fmt_t

MIN_KEEP = 0.12


def stumble_ranges(words, cfg):
    st = cfg["stumbles"]
    fillers = {norm(f) for f in st["fillers"]}
    flagged = {}  # index -> reden
    n = len(words)
    nw = [norm(w["text"]) for w in words]
    for i in range(n):
        if nw[i] in fillers:
            flagged[i] = "tussenwoord"
        elif words[i]["text"].endswith(("-", "–")) and i + 1 < n:
            flagged[i] = "afgebroken woord"
    if st.get("remove_repeats", True):
        i = 0
        while i < n:
            hit = 0
            for k in range(st.get("repeat_max_words", 3), 0, -1):
                if i + 2 * k <= n and nw[i:i + k] == nw[i + k:i + 2 * k] and all(nw[i:i + k]):
                    hit = k
                    break
            if hit:
                for j in range(i, i + hit):
                    flagged.setdefault(j, "herhaling")
                i += hit
            else:
                i += 1
    # groepeer opeenvolgende woorden tot cut-ranges
    out, i = [], 0
    idx = sorted(flagged)
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and idx[j + 1] == idx[j] + 1:
            j += 1
        a, b = idx[i], idx[j]
        prev_end = words[a - 1]["end"] if a > 0 else 0.0
        next_start = words[b + 1]["start"] if b + 1 < n else words[b]["end"]
        start = max(words[a]["start"], prev_end)
        end = min(words[b]["end"], next_start)
        text = " ".join(words[k]["text"] for k in range(a, b + 1))
        out.append({"start": round(start, 3), "end": round(end, 3), "kind": "stumble",
                    "reason": f"{flagged[a]}: \"{text}\"", "enabled": True})
        i = j + 1
    return out


def silence_cuts(media, words, cfg, total):
    s = cfg["silence"]
    cuts = []
    for a, b in silence_intervals(media, s["noise_db"], s["min_gap"]):
        at_start = a <= 0.05
        at_end = b is None or b >= total - 0.05
        b = total if b is None else b
        if at_start or at_end:
            if not s.get("trim_edges", True):
                continue
            keep = s.get("edge_keep", 0.1)
            cs, ce = (0.0, b - keep) if at_start else (a + keep, total)
            kind = "edge"
        else:
            half = s["keep_pause"] / 2
            cs, ce = a + half, b - half
            kind = "silence"
        if ce - cs < 0.05:
            continue
        mids = [w for w in words if cs < (w["start"] + w["end"]) / 2 < ce]
        if mids:  # stilte-detectie zegt stil, Whisper hoort woorden: niet knippen
            continue
        cuts.append({"start": round(cs, 3), "end": round(ce, 3), "kind": kind,
                     "reason": f"stilte {b - a:.2f}s", "enabled": True})
    return cuts


def plan(media, words, cfg, cuts_path):
    total = duration(media)
    cuts = []
    if not cfg["keep_silence"]:
        cuts += silence_cuts(media, words, cfg, total)
    if cfg["cut_stumbles"]:
        cuts += stumble_ranges(words, cfg)
    old = load_json(cuts_path)["cuts"] if Path(cuts_path).exists() else []
    manual = [c for c in old if c.get("kind") == "manual"]
    for c in cuts:  # bewaar eerdere "enabled: false" keuzes
        for o in old:
            if o.get("kind") == c["kind"] and abs(o["start"] - c["start"]) < 0.05 and not o.get("enabled", True):
                c["enabled"] = False
    cuts = sorted(cuts + manual, key=lambda c: c["start"])
    save_json(cuts_path, {"source_duration": round(total, 3), "cuts": cuts})
    return cuts, total


def keep_segments(cuts, total):
    rng = sorted((c["start"], c["end"]) for c in cuts if c.get("enabled", True))
    merged = []
    for s, e in rng:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    keep, pos = [], 0.0
    for s, e in merged:
        if s - pos >= MIN_KEEP:
            keep.append((pos, s))
        elif keep:
            keep[-1] = (keep[-1][0], s)  # te klein stukje: plak aan vorige
        pos = e
    if total - pos >= MIN_KEEP:
        keep.append((pos, total))
    return keep


def remap(words, keep):
    """Woordtijden naar de nieuwe tijdlijn. Woord blijft als zijn midden in een keep-segment valt."""
    offs, acc = [], 0.0
    for s, e in keep:
        offs.append(acc)
        acc += e - s
    out = []
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        for (s, e), off in zip(keep, offs):
            if s <= mid <= e:
                ns = off + max(w["start"], s) - s
                ne = off + min(w["end"], e) - s
                out.append({"text": w["text"], "start": ns, "end": max(ne, ns + 0.05)})
                break
    return out, acc


def describe(words, cuts):
    """Leesbaar transcript voor review: stumbles gemarkeerd, stiltes als [~1.2s]."""
    line, lines = [], []
    stumble = [c for c in cuts if c["kind"] == "stumble" and c.get("enabled", True)]
    sil = [c for c in cuts if c["kind"] in ("silence", "edge") and c.get("enabled", True)]
    marks = sorted([(w["start"], "w", w) for w in words] +
                   [(c["start"], "s", c) for c in sil], key=lambda m: (m[0], m[1]))
    start_t = None
    for t, kind, obj in marks:
        if start_t is None:
            start_t = t
        if kind == "s":
            line.append(f"[~{obj['end'] - obj['start']:.1f}s weg]")
        else:
            bad = any(c["start"] - 0.01 <= obj["start"] and obj["end"] <= c["end"] + 0.01 for c in stumble)
            line.append(f"⟦{obj['text']}⟧" if bad else obj["text"])
            if obj["text"].endswith((".", "?", "!")):
                lines.append(f"{fmt_t(start_t)}  " + " ".join(line))
                line, start_t = [], None
    if line:
        lines.append(f"{fmt_t(start_t)}  " + " ".join(line))
    return "\n".join(lines)
