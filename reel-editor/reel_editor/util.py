import json, re, subprocess, sys, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_json(p, data):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def deep_merge(base, over):
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def run(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"Commando mislukt: {' '.join(map(str, cmd))}\n{r.stderr[-1500:]}")
    return r


def probe(path):
    r = run(["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)])
    return json.loads(r.stdout)


def duration(path):
    return float(probe(path)["format"]["duration"])


def norm(word):
    """Vergelijkingsvorm van een woord: kleine letters, zonder leestekens."""
    return re.sub(r"[^\w]", "", word.lower())


def fmt_t(t):
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def silence_intervals(media, noise_db, min_dur):
    """Stiltes uit de audio zelf (ffmpeg silencedetect). Betrouwbaarder dan Whisper-woordgrenzen."""
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(media), "-vn",
             "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    out = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        out.append((max(s, 0.0), e))
    return out
