import os
import sys
import asyncio
import argparse
from pathlib import Path

# Kiểm tra và import thư viện edge-tts
try:
    import edge_tts
except ImportError:
    print("[!] Chưa cài đặt thư viện edge-tts. Hãy chạy lệnh: pip install edge-tts")
    sys.exit(1)

VOICE = "vi-VN-HoaiMyNeural"  # Giọng Hoài My (Nữ miền Bắc)

def parse_rate(rate_str):
    """
    Tự động chuyển đổi tốc độ từ dạng số thập phân (ví dụ: 1.12, 1.5, 0.9) 
    hoặc chuỗi phần trăm (ví dụ: +20%, -10%) sang định dạng chuẩn của edge-tts.
    """
    rate_str = str(rate_str).strip()
    
    # Nếu đã có dấu % (ví dụ: +20%, -10%)
    if rate_str.endswith('%'):
        if not rate_str.startswith('+') and not rate_str.startswith('-'):
            rate_str = '+' + rate_str
        return rate_str
    
    # Nếu là dạng số thập phân (ví dụ: 1.12, 0.9, 2.0)
    try:
        val = float(rate_str)
        percentage = int(round((val - 1.0) * 100))
        if percentage >= 0:
            return f"+{percentage}%"
        else:
            return f"{percentage}%"
    except ValueError:
        # Mặc định nếu không parse được
        return "+0%"

async def text_to_speech(text, output_path, rate="+0%", pitch="+0Hz"):
    """
    Hàm gọi API Edge TTS với tùy chỉnh tốc độ (rate) và xử lý chống lỗi rỗng file.
    """
    communicate = edge_tts.Communicate(text, VOICE, rate=rate, pitch=pitch)
    await communicate.save(str(output_path))

    # Kiểm tra xem file xuất ra có dung lượng thật không
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise Exception("File audio tạo ra bị rỗng (0 byte).")

def main():
    parser = argparse.ArgumentParser(description="Tool tạo giọng đọc Hoài My (Edge-TTS) có tùy chỉnh tốc độ.")
    parser.add_argument("-o", "--output", type=str, default="out/tts_hoaimy", help="Đường dẫn thư mục lưu file MP3 đầu ra")
    parser.add_argument("-s", "--speed", type=str, default="1.0", help="Tốc độ đọc (Hỗ trợ số như 1.12, 1.5 hoặc phần trăm như +20%, -10%)")
    args = parser.parse_args()

    # Hỗ trợ hiển thị và nhập tiếng Việt chuẩn trên Windows Terminal/CMD
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stdin.reconfigure(encoding='utf-8')
        except AttributeError:
            pass

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Xử lý chuẩn hóa tốc độ
    rate = parse_rate(args.speed)

    print("==================================================")
    print("      TOOL TẠO GIỌNG ĐỌC HOÀI MY (EDGE-TTS)       ")
    print("==================================================")
    print(f"[*] Giọng đọc đang dùng: {VOICE}")
    print(f"[*] Tốc độ đọc cấu hình: {args.speed} -> Quy đổi (Rate): {rate}")
    print(f"[*] Thư mục đầu ra: {output_dir.resolve()}")
    print("[*] Nhập 'exit' hoặc 'quit' để thoát chương trình.\n")

    counter = 1
    while True:
        try:
            text = input(f"[{counter}] Nhập văn bản cần đọc: ").strip()
            
            if not text:
                continue
            if text.lower() in ["exit", "quit"]:
                print("Tạm biệt anh!")
                break

            safe_name = "".join(c if c.isalnum() else "_" for c in text[:15])
            output_filename = f"{counter:02d}_{safe_name}.mp3"
            output_path = output_dir / output_filename

            print(f"   -> Đang tạo giọng đọc Hoài My (tốc độ {args.speed})...")
            
            max_retries = 3
            for attempt in range(1, max_retries + 1):
                try:
                    asyncio.run(text_to_speech(text, output_path, rate=rate))
                    print(f"   -> [X] Thành công! Đã lưu tại: {output_path.resolve()}\n")
                    counter += 1
                    break
                except Exception as e:
                    if attempt < max_retries:
                        print(f"   -> [!] Lỗi kết nối (Thử lại lần {attempt}/{max_retries})...")
                        asyncio.run(asyncio.sleep(1))
                    else:
                        raise e

        except KeyboardInterrupt:
            print("\nThoát chương trình.")
            break
        except Exception as e:
            print(f"   -> [!] Lỗi xảy ra: {e}\n")

if __name__ == "__main__":
    main()
