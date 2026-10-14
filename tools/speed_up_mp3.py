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
    FFMPEG_BIN = "ffmpeg" # Fallback về lệnh hệ thống nếu chưa cài thư viện

def speed_up_mp3(input_path, output_path, speed=1.5):
    """
    Hàm gọi FFmpeg để tăng tốc độ file MP3 giữ nguyên giọng và giữ nguyên tên file.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        FFMPEG_BIN,
        '-i', str(input_path),
        '-filter:a', f'atempo={speed}',
        '-y',  # Tự động ghi đè nếu file đầu ra đã tồn tại
        str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            print(f"[X] Xong: {input_path.name}")
        else:
            print(f"[!] Lỗi ở file {input_path.name}:")
            print(result.stderr)
    except FileNotFoundError:
        print("[!] Không tìm thấy FFmpeg! Hãy chắc chắn bạn đã chạy lệnh: pip install imageio-ffmpeg")

def main():
    parser = argparse.ArgumentParser(description="Tool tăng tốc độ file MP3, giữ nguyên tên và cấu trúc thư mục.")
    parser.add_argument("input_dir", type=str, help="Đường dẫn thư mục chứa file MP3 đầu vào")
    parser.add_argument("output_dir", type=str, help="Đường dẫn thư mục lưu file MP3 đầu ra")
    parser.add_argument("-s", "--speed", type=float, default=1.5, help="Tốc độ muốn tăng (Mặc định: 1.5)")

    args = parser.parse_args()

    input_path = Path(args.input_dir)
    output_path = Path(args.output_dir)
    speed = args.speed

    # Kiểm tra tính hợp lệ của thư mục nguồn
    if not input_path.exists() or not input_path.is_dir():
        print(f"[!] Thư mục đầu vào không tồn tại hoặc không hợp lệ: {input_path}")
        sys.exit(1)

    # Kiểm tra điều kiện: Không được trùng thư mục in và out
    if input_path.resolve() == output_path.resolve():
        print(f"[!] Lỗi: Thư mục đầu vào và đầu ra không được trùng nhau!")
        sys.exit(1)

    all_mp3_files = list(input_path.rglob("*.mp3"))
    mp3_files = [f for f in all_mp3_files if output_path not in f.parents and f.parent != output_path]

    if not mp3_files:
        print(f"[!] Không tìm thấy file .mp3 nào trong thư mục: {input_path}")
        return

    print(f"\n[+] Tìm thấy tổng cộng {len(mp3_files)} file MP3. Đang xử lý với tốc độ {speed}x...")
    
    for file in mp3_files:
        relative_path = file.relative_to(input_path)
        # Giữ nguyên tên file gốc (file.name)
        target_file_path = output_path / relative_path.parent / file.name
        
        print(f"Đang xử lý: {relative_path}...")
        speed_up_mp3(file, target_file_path, speed)
        
    print(f"\n[+] Hoàn tất toàn bộ! Các file đã xử lý được lưu tại:\n    {output_path.resolve()}")

if __name__ == "__main__":
    main()
