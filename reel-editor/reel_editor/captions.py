"""Captions, titel en CTA als ASS-ondertitels (libass in ffmpeg). Stijl komt volledig uit config."""
import math, textwrap


def _ass_color(hexcol):
    h = hexcol.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _t(sec):
    sec = max(sec, 0)
    cs = int(round(sec * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _esc(text):
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def _wrap(text, width):
    return "\\N".join(textwrap.wrap(text, width=width, break_long_words=False) or [""])


def _split_even(words, max_chars):
    """Splits één zin in gelijke delen als hij te lang is. Voegt nooit twee zinnen samen."""
    total = sum(len(w["text"]) + 1 for w in words)
    k = max(1, math.ceil(total / max_chars))
    if k == 1:
        return [words]
    target, parts, cur, cur_len = total / k, [], [], 0
    for w in words:
        cur.append(w)
        cur_len += len(w["text"]) + 1
        if cur_len >= target and len(parts) < k - 1:
            parts.append(cur)
            cur, cur_len = [], 0
    if cur:
        parts.append(cur)
    return parts


def sentence_events(words, style, total):
    sentences, cur = [], []
    for w in words:
        cur.append(w)
        if w["text"].endswith((".", "?", "!", "…")):
            sentences.append(cur)
            cur = []
    if cur:
        sentences.append(cur)
    groups = []
    for s in sentences:
        groups += _split_even(s, style["max_chars_per_caption"])
    return _finish(groups, style, total, lambda g: " ".join(w["text"] for w in g))


def word_events(words, style, total):
    return _finish([[w] for w in words], style, total, lambda g: g[0]["text"])


def _finish(groups, style, total, joiner):
    ev = []
    for g in groups:
        ev.append({"start": g[0]["start"], "end": g[-1]["end"], "text": joiner(g)})
    for i, e in enumerate(ev):
        nxt = ev[i + 1]["start"] if i + 1 < len(ev) else total
        e["end"] = min(e["end"] + style["hold"], nxt) if nxt > e["start"] else e["end"]
        if e["end"] - e["start"] < 0.08:
            e["end"] = e["start"] + 0.08
    return ev


def capitalize_sentences(words):
    """Eerste woord van elke zin krijgt een hoofdletter (ook als de zin begon met een weggeknipt tussenwoord)."""
    out, start = [], True
    for w in words:
        t = w["text"]
        if start and t:
            t = t[0].upper() + t[1:]
        out.append(dict(w, text=t))
        start = t.endswith((".", "?", "!", "…"))
    return out


def build_events(words, cfg, total):
    """Geeft lijst van {kind,start,end,text}."""
    st = cfg["style"]
    mode = cfg["caption_mode"]
    if st["caption"].get("capitalize"):
        words = capitalize_sentences(words)
    events = []
    if mode == "sentence":
        events += [dict(e, kind="caption") for e in sentence_events(words, st["caption"], total)]
    elif mode == "word":
        events += [dict(e, kind="caption") for e in word_events(words, st["caption"], total)]
    elif mode != "none":
        raise SystemExit(f'caption_mode moet "none", "sentence" of "word" zijn, niet "{mode}"')
    if cfg.get("title"):
        end = total if not cfg.get("title_seconds") else min(cfg["title_seconds"], total)
        events.append({"kind": "title", "start": 0.0, "end": end, "text": cfg["title"]})
    if cfg.get("cta"):
        s = max(0.0, total - cfg.get("cta_seconds", 3.0))
        events.append({"kind": "cta", "start": s, "end": total, "text": cfg["cta"]})
    return events


def write_ass(events, cfg, path):
    o, st = cfg["output"], cfg["style"]
    W, H = o["width"], o["height"]
    names = {"caption": "Caption", "title": "Title", "cta": "CTA"}
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
             "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
             "[V4+ Styles]",
             "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
             "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
             "Alignment,MarginL,MarginR,MarginV,Encoding"]
    for kind, name in names.items():
        s = st[kind]
        if s.get("box_color"):  # effen balk achter de tekst (BorderStyle 3): outline-kleur wordt balkkleur
            s = dict(s, outline_color=s["box_color"], outline=s.get("box_padding", 16))
            bstyle = 3
        else:
            bstyle = 1
        lines.append(
            f"Style: {name},{st['font']},{s['size']},{_ass_color(s['color'])},&H000000FF,"
            f"{_ass_color(s['outline_color'])},&H00000000,{-1 if s['bold'] else 0},0,0,0,100,100,0,0,{bstyle},"
            f"{s['outline']},{s['shadow']},5,60,60,0,1")
    lines += ["", "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
    for e in sorted(events, key=lambda e: e["start"]):
        s = st[e["kind"]]
        text = e["text"].upper() if s.get("uppercase") else e["text"]
        width = s.get("max_chars_per_line", 22)
        y = int(H * s["y"])
        lines.append(f"Dialogue: 0,{_t(e['start'])},{_t(e['end'])},{names[e['kind']]},,0,0,0,,"
                     f"{{\\an5\\pos({W // 2},{y})}}{_wrap(_esc(text), width)}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
