"""Rendert: knippen (trim/concat) -> 9:16 crop -> captions/titel/CTA (libass) -> h264/aac."""
import time
from pathlib import Path
from .util import run, ROOT
from .cuts import keep_segments, remap
from .captions import build_events, write_ass

FADE = 0.012  # korte audio-fade op elke snede tegen klikjes


def _esc_filter(p):
    return str(p).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def render(job_dir, source, words, cuts, total, cfg, out_path):
    job_dir = Path(job_dir)
    keep = keep_segments(cuts, total)
    if not keep:
        raise SystemExit("Alles weggeknipt: controleer cuts.json.")
    tl_words, new_total = remap(words, keep)
    events = build_events(tl_words, cfg, new_total)
    write_ass(events, cfg, job_dir / "captions.ass")

    o = cfg["output"]
    W, H = o["width"], o["height"]
    parts, v_in, a_in = [], [], []
    for i, (s, e) in enumerate(keep):
        d = e - s
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}]")
        f = min(FADE, d / 4)
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d={f:.3f},afade=t=out:st={d - f:.3f}:d={f:.3f}[a{i}]")
        v_in.append(f"[v{i}]")
        a_in.append(f"[a{i}]")
    n = len(keep)
    parts.append("".join(f"{v}{a}" for v, a in zip(v_in, a_in)) + f"concat=n={n}:v=1:a=1[vc][ac]")
    fonts = _esc_filter((ROOT / cfg["style"]["fonts_dir"]).resolve())
    parts.append(
        f"[vc]scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H}:x='(iw-ow)*{o['crop_x']}':y='(ih-oh)/2',setsar=1,fps={o['fps']},"
        f"subtitles=captions.ass:fontsdir='{fonts}'[vout]")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
         "-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[ac]",
         "-c:v", "libx264", "-crf", str(o["crf"]), "-preset", o["preset"], "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out_path.resolve())],
        cwd=job_dir)
    return {"keep": keep, "expected_duration": new_total, "events": events,
            "render_seconds": round(time.time() - t0, 1)}
