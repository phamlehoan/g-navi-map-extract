import os
import sys
import argparse
import subprocess
from pathlib import Path

try:
    import imageio_ffmpeg
    FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()
except ImportError:
    FFMPEG_BIN = "ffmpeg"

def parse_time_to_seconds(t_str):
    """Chuyển đổi chuỗi thời gian (giây hoặc HH:MM:SS) sang tổng số giây (float)."""
    if t_str is None:
        return None
    t_str = str(t_str).strip()
    if ':' in t_str:
        parts = t_str.split(':')
        try:
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
        except ValueError:
            pass
    try:
        return float(t_str)
    except ValueError:
        return 0.0

def cut_audio(input_path, output_path, start="0", end=None, duration=None, force=False):
    """
    Hàm gọi FFmpeg để cắt đoạn âm thanh có tự động tính toán thời lượng và xử lý ghi đè chuẩn xác.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Kiểm tra xem file đầu ra đã tồn tại chưa
    if output_path.exists() and not force:
        print(f"[!] CẢNH BÁO: File đầu ra đã tồn tại: {output_path.name}")
        choice = input("    Bạn có muốn ghi đè lên file này không? (y/N): ").strip().lower()
        if choice != 'y':
            print(f"[x] Đã hủy bỏ việc ghi đè file: {output_path.name}")
            return False
        else:
            # QUAN TRỌNG: Khi người dùng đồng ý 'y', bật cờ force thành True để FFmpeg nhận lệnh -y
            force = True

    # Tự động tính toán thời lượng nếu người dùng truyền cả start và end
    if end is not None and duration is None:
        start_sec = parse_time_to_seconds(start)
        end_sec = parse_time_to_seconds(end)
        if end_sec <= start_sec:
            print(f"[!] Lỗi: Thời gian kết thúc ({end}) phải lớn hơn thời gian bắt đầu ({start})!")
            return False
        calculated_duration = end_sec - start_sec
        duration = str(calculated_duration)

    cmd = [FFMPEG_BIN]
    if start:
        cmd.extend(['-ss', str(start)])
        
    cmd.extend(['-i', str(input_path)])
    
    if duration:
        cmd.extend(['-t', str(duration)])
    elif end:
        cmd.extend(['-to', str(end)])
        
    # Nếu có cờ force (hoặc đã bấm y), gắn -y vào lệnh FFmpeg để cho phép ghi đè
    if force:
        cmd.append('-y')
        
    cmd.append(str(output_path))
    
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            print(f"[X] Xong: {output_path.name}")
            return True
        else:
            print(f"[!] Lỗi ở file {input_path.name}:")
            print(result.stderr)
            return False
    except FileNotFoundError:
        print("[!] Không tìm thấy FFmpeg! Hãy chạy lệnh: pip install imageio-ffmpeg")
        return False

def main():
    parser = argparse.ArgumentParser(description="Tool cắt file âm thanh MP3 chính xác, thông minh.")
    parser.add_argument("input_path", type=str, help="Đường dẫn file MP3 hoặc thư mục đầu vào")
    parser.add_argument("output_path", type=str, help="Đường dẫn file/thư mục đầu ra")
    parser.add_argument("-st", "--start", type=str, default="0", help="Thời điểm bắt đầu (ví dụ: 3)")
    parser.add_argument("-et", "--end", type=str, default=None, help="Thời điểm kết thúc (ví dụ: 11)")
    parser.add_argument("-d", "--duration", type=str, default=None, help="Hoặc nhập trực tiếp thời lượng cần lấy")
    parser.add_argument("-f", "--force", action="store_true", help="Buộc ghi đè nếu file đầu ra đã tồn tại mà không cần hỏi")

    args = parser.parse_args()

    input_path = Path(args.input_path)
    output_path = Path(args.output_path)
    start = args.start
    end = args.end
    duration = args.duration
    force = args.force

    if not input_path.exists():
        print(f"[!] Đường dẫn đầu vào không tồn tại: {input_path}")
        sys.exit(1)

    if input_path.is_file():
        if input_path.resolve() == output_path.resolve():
            print(f"[!] LỖI AN TOÀN: File đầu ra không được trùng với file đầu vào!")
            sys.exit(1)
            
        print(f"\n[+] Đang cắt file từ {start}s đến {end}s...")
        cut_audio(input_path, output_path, start, end, duration, force)

    elif input_path.is_dir():
        if input_path.resolve() == output_path.resolve():
            print(f"[!] LỖI AN TOÀN: Thư mục đầu vào và đầu ra không được trùng nhau!")
            sys.exit(1)
            
        all_mp3_files = list(input_path.rglob("*.mp3"))
        mp3_files = [f for f in all_mp3_files if output_path not in f.parents and f.parent != output_path]

        if not mp3_files:
            print(f"[!] Không tìm thấy file .mp3 nào trong thư mục: {input_path}")
            return

        print(f"\n[+] Tìm thấy tổng cộng {len(mp3_files)} file MP3. Đang tiến hành cắt...")
        for file in mp3_files:
            relative_path = file.relative_to(input_path)
            target_file_path = output_path / relative_path.parent / file.name
            print(f"Đang cắt: {relative_path}...")
            cut_audio(file, target_file_path, start, end, duration, force)
            
        print(f"\n[+] Hoàn tất toàn bộ!")

if __name__ == "__main__":
    main()
