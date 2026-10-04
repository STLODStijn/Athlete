"""Lokale transcriptie met faster-whisper (woordtijden). Niets verlaat de machine
behalve de eenmalige modeldownload van Hugging Face."""
import re
from pathlib import Path
from .util import run, save_json, load_json, norm


def extract_audio(video, wav):
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", str(wav)])


def transcribe(media, cfg, model_override=None):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit("faster-whisper ontbreekt. Draai eerst ./setup.sh")
    model_name = model_override or cfg["whisper_model"]
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    prompt = ", ".join(cfg.get("terms", [])) or None
    segments, info = model.transcribe(
        str(media), language=cfg["language"], word_timestamps=True,
        initial_prompt=prompt, vad_filter=False, condition_on_previous_text=False)
    words = []
    for seg in segments:
        for w in seg.words or []:
            t = w.word.strip()
            if t:
                words.append({"text": t, "start": round(w.start, 3), "end": round(w.end, 3)})
    return {"model": model_name, "language": info.language, "words": words}


def apply_spelling(words, spelling):
    """Vervang woorden/zinsdelen volgens cfg['spelling'] (fout -> juist).
    Hoofdletterongevoelig, leestekens aan het eind blijven behouden."""
    rules = []
    for wrong, right in spelling.items():
        toks = [norm(t) for t in wrong.split()]
        if toks and all(toks):
            rules.append((toks, right))
    rules.sort(key=lambda r: -len(r[0]))
    out, i = [], 0
    while i < len(words):
        hit = None
        for toks, right in rules:
            n = len(toks)
            if [norm(w["text"]) for w in words[i:i + n]] == toks:
                hit = (n, right)
                break
        if hit:
            n, right = hit
            tail = re.search(r"[^\w]+$", words[i + n - 1]["text"])
            out.append({"text": right + (tail.group(0) if tail else ""),
                        "start": words[i]["start"], "end": words[i + n - 1]["end"]})
            i += n
        else:
            out.append(dict(words[i]))
            i += 1
    for k, w in enumerate(out):
        w["i"] = k
    return out


def load_words(job_dir, cfg):
    raw = load_json(Path(job_dir) / "transcript.raw.json")
    return apply_spelling(raw["words"], cfg.get("spelling", {}))
