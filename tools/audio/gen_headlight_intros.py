# -*- coding: utf-8 -*-
"""Sinh 2 câu nhắc đèn (Hoài My, rate 1.2) rồi tăng volume ×3 → out/sounds."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out" / "sounds"
TMP = ROOT / "analyze" / "tts_headlight_tmp"

VOICE = "vi-VN-HoaiMyNeural"
RATE = "+20%"  # 1.2×
GAIN = 3.0

PHRASES = [
    ("troi_da_toi.mp3", "Trời đã tối"),
    ("neu_vao_ham.mp3", "Nếu vào hầm"),
]

try:
    import edge_tts
except ImportError:
    print("[!] pip install edge-tts")
    sys.exit(1)

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG = "ffmpeg"


async def tts(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    await edge_tts.Communicate(text, VOICE, rate=RATE).save(str(path))
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"TTS rỗng: {path}")


def amplify(src: Path, dst: Path, gain: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error",
        "-i", str(src),
        "-filter:a", f"volume={gain}",
        "-codec:a", "libmp3lame", "-q:a", "4",
        "-y", str(dst),
    ]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "ffmpeg fail")


async def main_async() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    TMP.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in PHRASES:
        raw = TMP / name
        final = OUT / name
        print(f"[*] TTS: {text!r} → {name}")
        await tts(text, raw)
        print(f"[*] volume ×{GAIN} → {final}")
        amplify(raw, final, GAIN)
        print(f"[X] {final} ({final.stat().st_size} bytes)")


if __name__ == "__main__":
    asyncio.run(main_async())
