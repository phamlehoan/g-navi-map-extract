# -*- coding: utf-8 -*-
"""
Tăng/giảm âm lượng hàng loạt file MP3 (ffmpeg volume filter).
Giữ nguyên cấu trúc thư mục con.

Ví dụ:
  python tools/audio/volume_mp3.py data_source/sounds out/sounds -g 5
  python tools/audio/volume_mp3.py data_source/sounds out/sounds --gain 0.5
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_BIN = "ffmpeg"


def amplify_one(src: Path, dst: Path, gain: float) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    # volume=<linear gain>; gain=5 → to hơn 5 lần (có thể clip nếu nguồn đã to)
    filt = f"volume={gain}"
    cmd = [
        FFMPEG_BIN,
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(src),
        "-filter:a", filt,
        "-codec:a", "libmp3lame",
        "-q:a", "4",
        "-y",
        str(dst),
    ]
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        print("[!] Không tìm thấy FFmpeg. Cài: pip install imageio-ffmpeg")
        return False
    if r.returncode != 0:
        print(f"[!] Lỗi {src.name}: {r.stderr.strip()}")
        return False
    print(f"[X] {dst}")
    return True


def main() -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    p = argparse.ArgumentParser(description="Tăng/giảm âm lượng toàn bộ MP3 trong thư mục.")
    p.add_argument("input_dir", type=str, help="Thư mục nguồn (vd. data_source/sounds)")
    p.add_argument("output_dir", type=str, help="Thư mục đích (vd. out/sounds)")
    p.add_argument(
        "-g", "--gain",
        type=float,
        default=5.0,
        help="Hệ số âm lượng tuyến tính (mặc định 5 = gấp 5 lần). <1 để giảm.",
    )
    args = p.parse_args()

    if args.gain <= 0:
        print("[!] --gain phải > 0")
        return 1

    inp = Path(args.input_dir)
    out = Path(args.output_dir)
    if not inp.is_dir():
        print(f"[!] Không có thư mục nguồn: {inp}")
        return 1
    if inp.resolve() == out.resolve():
        print("[!] input_dir và output_dir không được trùng")
        return 1

    files = [f for f in inp.rglob("*.mp3") if out.resolve() not in f.resolve().parents]
    if not files:
        print(f"[!] Không có file .mp3 trong {inp}")
        return 1

    print(f"[+] {len(files)} file MP3, gain={args.gain}x → {out.resolve()}")
    ok = 0
    for f in files:
        rel = f.relative_to(inp)
        dst = out / rel
        print(f"… {rel}")
        if amplify_one(f, dst, args.gain):
            ok += 1
    print(f"[+] Xong {ok}/{len(files)} → {out.resolve()}")
    return 0 if ok == len(files) else 2


if __name__ == "__main__":
    sys.exit(main())
