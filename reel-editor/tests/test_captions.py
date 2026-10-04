"""Regressie: lange titel/CTA moeten met een echte ASS-regelbreuk (\\N) afbreken, niet met '/N'."""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reel_editor.captions import write_ass
from reel_editor.util import load_json, ROOT

cfg = load_json(ROOT / "config.default.json")
ev = [{"kind": "cta", "start": 0, "end": 2, "text": "cravings, dan heb ik een ebook voor je en meer."}]
with tempfile.TemporaryDirectory() as t:
    p = Path(t) / "x.ass"
    write_ass(ev, cfg, p)
    txt = p.read_text(encoding="utf-8")
assert "/N" not in txt, "regelbreuk is kapot geescaped"
assert "\\N" in txt, "lange CTA is niet afgebroken"

# monoline: lange zin wordt in stukken gesplitst, elk stuk past op een regel, geen \\N in captions
from reel_editor.captions import build_events, caption_limit
words, tt = [], 0.0
for w in "Als je aan me thuis komt, heb je dan last cravings, dan heb ik een ebook voor je.".split():
    words.append({"text": w, "start": tt, "end": tt + 0.3}); tt += 0.35
cfg["caption_mode"] = "sentence"
caps = [e for e in build_events(words, cfg, tt) if e["kind"] == "caption"]
assert len(caps) >= 2
assert all(len(e["text"]) <= caption_limit(cfg) for e in caps), [e["text"] for e in caps]
with tempfile.TemporaryDirectory() as t2:
    p = Path(t2) / "y.ass"; write_ass(caps, cfg, p)
    assert "\\N" not in "".join(l for l in p.read_text(encoding="utf-8").splitlines() if "Dialogue" in l)
print("OK")
