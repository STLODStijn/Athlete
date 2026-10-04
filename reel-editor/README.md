# reel-editor (fase 1)

Lokale pipeline: ruwe talking-head video -> bewerkte 9:16 reel. Alles draait op je eigen machine.

## Installatie (macOS)
    ./setup.sh        # ffmpeg via Homebrew + Python venv + faster-whisper
Het Whisper-model wordt bij de eerste transcriptie eenmalig gedownload (enige netwerkverkeer).

## Snelste weg (aanbevolen)
    ./reel go ~/reels/raw/video.MOV --name mijnreel --title "Titel" --cta "Reageer met het woord ebook"
Eén commando: transcribeert, toont het transcript, laat je spelling/titel/CTA/captionmodus aanpassen,
vraagt goedkeuring, rendert, controleert, opent de reel en kopieert een rapport naar je klembord.
    ./reel report mijnreel      # kopieert alles wat Claude nodig heeft naar het klembord (macOS)

## Werkwijze (losse stappen)
    ./reel transcribe ~/pad/video.mov --name mijnreel   # transcript + voorstel knipplan
    ./reel review mijnreel                               # lees transcript, ⟦stumbles⟧ en stiltes
    ./reel fix mijnreel "bionde" "Beyond"                # spelling corrigeren (herberekent plan)
    ./reel approve mijnreel                              # jouw goedkeuring (render weigert zonder)
    ./reel render mijnreel                               # -> jobs/mijnreel/out/mijnreel.mp4
    ./reel verify mijnreel [--deep]                      # controle; --deep transcribeert de uitvoer opnieuw

Per video pas je `jobs/<naam>/config.json` aan. Alleen wat je daar zet overschrijft `config.default.json`:
`keep_silence`, `cut_stumbles`, `caption_mode` (none|sentence|word), `title`, `cta`, `silence.*`, `style.*`, `whisper_model`.
`keep_silence: true` zet alleen stilte-knippen uit; stumbles blijven apart schakelbaar via `cut_stumbles`.
Knippen bijsturen: `jobs/<naam>/cuts.json` (`"enabled": false`, of een eigen cut met `"kind": "manual"`).

## Structuur (uitbreidbaar voor fase 2)
    reel_editor/   transcribe.py cuts.py captions.py render.py verify.py cli.py
    assets/        fonts/ (zet je lettertype hier) sfx/ backgrounds/ (leeg, voor later)
    jobs/<naam>/   config.json, transcript.raw.json, cuts.json, captions.ass, out/, verify/
Nieuwe functies (kleurcorrectie, sfx, animaties, achtergrond) = nieuwe module + een stap in `render.render()`.

## Bekende beperkingen
- Stumble-detectie is heuristisch (tussenwoorden, directe herhalingen). Opzettelijke herhaling ("heel, heel belangrijk") wordt ook gemarkeerd: daarom review vóór render.
- faster-whisper draait op Mac op CPU (geen Metal). Snelheid: zie timings.json na je eerste run.
- Stijlwaarden in config.default.json zijn placeholders (Arial, wit/geel).
