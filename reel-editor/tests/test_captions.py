"""Regressie: lange captions moeten met een echte ASS-regelbreuk (\\N) afbreken, niet met '/N'."""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reel_editor.captions import write_ass
from reel_editor.util import load_json, ROOT

cfg = load_json(ROOT / "config.default.json")
ev = [{"kind": "caption", "start": 0, "end": 2, "text": "cravings, dan heb ik een ebook voor je."}]
with tempfile.TemporaryDirectory() as t:
    p = Path(t) / "x.ass"
    write_ass(ev, cfg, p)
    txt = p.read_text(encoding="utf-8")
assert "/N" not in txt, "regelbreuk is kapot geescaped"
assert "\\N" in txt, "lange caption is niet afgebroken"
print("OK")
