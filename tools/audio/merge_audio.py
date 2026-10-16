import os
import sys
import argparse
import subprocess
from pathlib import Path

# Tự động lấy file ffmpeg được đóng gói sẵn trong thư viện python
try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_BIN = "ffmpeg"

def mix_audio(voice_path, bgm_path, output_path, bg_volume=0.15):
    """
    Hàm gọi FFmpeg để trộn file thoại và nhạc nền.
    - voice_path: File giọng đọc (chính)
    - bgm_path: File nhạc nền (phụ)
    - bg_volume: Âm lượng nhạc nền (0.15 = 15% để không át tiếng thoại)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # FFmpeg filter complex:
    # [0:a] là file thoại, [1:a] là nhạc nền
    # Giảm âm lượng nhạc nền xuống bg_volume, sau đó trộn với file thoại (độ dài lấy theo file thoại: duration=first)
    filter_complex = f"[1:a]volume={bg_volume}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[out]"
    
    cmd = [
        FFMPEG_BIN,
        '-i', str(voice_path),
        '-i', str(bgm_path),
        '-filter_complex', filter_complex,
        '-map', '[out]',
        '-y',  # Ghi đè nếu file đầu ra đã có sẵn
        str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            print(f"[X] Xong: {voice_path.name}")
        else:
            print(f"[!] Lỗi ở file {voice_path.name}:")
            print(result.stderr)
    except FileNotFoundError:
        print("[!] Không tìm thấy FFmpeg! Hãy chắc chắn bạn đã chạy lệnh: pip install imageio-ffmpeg")

def main():
    parser = argparse.ArgumentParser(description="Tool ghép nhạc nền vào file thoại MP3 tự động.")
    parser.add_argument("voice_input", type=str, help="Đường dẫn file thoại lẻ hoặc thư mục chứa các file thoại MP3")
    parser.add_argument("bgm_file", type=str, help="Đường dẫn file MP3 nhạc nền")
    parser.add_argument("output_path", type=str, help="Đường dẫn file đầu ra (nếu input là file) hoặc thư mục đầu ra (nếu input là thư mục)")
    parser.add_argument("--bg-vol", type=float, default=0.15, help="Âm lượng nhạc nền từ 0.0 đến 1.0 (Mặc định: 0.15)")

    args = parser.parse_args()

    voice_input = Path(args.voice_input)
    bgm_path = Path(args.bgm_file)
    output_path = Path(args.output_path)
    bg_vol = args.bg_vol

    # Kiểm tra file nhạc nền
    if not bgm_path.exists() or not bgm_path.is_file():
        print(f"[!] File nhạc nền không tồn tại hoặc không hợp lệ: {bgm_path}")
        sys.exit(1)

    # Kiểm tra đầu vào thoại
    if not voice_input.exists():
        print(f"[!] Đường dẫn thoại đầu vào không tồn tại: {voice_input}")
        sys.exit(1)

    # Trường hợp 1: Đầu vào là 1 file thoại lẻ
    if voice_input.is_file():
        print(f"\n[+] Đang ghép nhạc nền vào file thoại: {voice_input.name}...")
        mix_audio(voice_input, bgm_path, output_path, bg_vol)
        print(f"[+] Hoàn tất! File lưu tại: {output_path.resolve()}")

    # Trường hợp 2: Đầu vào là cả một thư mục thoại (Batch processing)
    elif voice_input.is_dir():
        if voice_input.resolve() == output_path.resolve():
            print(f"[!] Lỗi: Thư mục đầu vào và đầu ra không được trùng nhau!")
            sys.exit(1)
            
        all_mp3_files = list(voice_input.rglob("*.mp3"))
        voice_files = [f for f in all_mp3_files if output_path not in f.parents and f.parent != output_path]

        if not voice_files:
            print(f"[!] Không tìm thấy file .mp3 nào trong thư mục thoại: {voice_input}")
            return

        print(f"\n[+] Tìm thấy tổng cộng {len(voice_files)} file thoại. Đang tiến hành ghép nhạc nền...")
        
        for file in voice_files:
            relative_path = file.relative_to(voice_input)
            target_file_path = output_path / relative_path.parent / file.name
            
            print(f"Đang ghép: {relative_path}...")
            mix_audio(file, bgm_path, target_file_path, bg_vol)
            
        print(f"\n[+] Hoàn tất toàn bộ! Các file đã ghép được lưu tại:\n    {output_path.resolve()}")

if __name__ == "__main__":
    main()
