#!/usr/bin/env bash
# Installeert alleen lokaal: ffmpeg (Homebrew) + Python venv met faster-whisper. Niets wordt geüpload.
set -euo pipefail
cd "$(dirname "$0")"
command -v brew >/dev/null || { echo "Homebrew ontbreekt: https://brew.sh"; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg installeren via Homebrew..."; brew install ffmpeg; }
FILTERS="$(ffmpeg -hide_banner -filters 2>/dev/null || true)"
echo "$FILTERS" | grep -Eq " subtitles " || { echo "Jouw ffmpeg mist libass (subtitles-filter). Oplossing: brew uninstall ffmpeg && brew install ffmpeg-full"; exit 1; }
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip faster-whisper
echo "Klaar. Het Whisper-model wordt bij de eerste transcriptie eenmalig gedownload."
echo "Test: ./reel transcribe pad/naar/video.mov"
