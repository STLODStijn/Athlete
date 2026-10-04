"""Synthetisch testbestand: horizontale video, 'spraak' = toonbursts met bekende woordtijden.
Test de pipeline-logica (knippen, remap, captions, titel, CTA). Test NIET Whisper of Stijns stem."""
import json, math, struct, subprocess, sys, wave
from pathlib import Path

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
SR, DUR = 16000, 9.0
words = [("Dit",.8,1.1),("is",1.2,1.4),("de",1.5,1.7),("de",1.8,2.0),("waarheid.",2.1,2.7),
         ("Euh",4.2,4.5),("stop",4.6,4.9),("met",5.0,5.2),("snacken.",5.3,5.9),
         ("Bionde",6.9,7.3),("coacht",7.4,7.8),("je.",7.9,8.2)]
samples = [0.0] * int(SR * DUR)
for k, (_, s, e) in enumerate(words):
    f = 200 + 60 * k
    for n in range(int(s * SR), int(e * SR)):
        samples[n] = 0.4 * math.sin(2 * math.pi * f * n / SR)
with wave.open(str(out / "a.wav"), "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(b"".join(struct.pack("<h", int(x * 32767)) for x in samples))
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={DUR}",
                "-i", str(out / "a.wav"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-shortest", str(out / "raw.mp4")], check=True)
json.dump({"model": "synthetic", "language": "nl",
           "words": [{"text": t, "start": s, "end": e} for t, s, e in words]},
          open(out / "transcript.raw.json", "w"))
print("fixture klaar", out)
