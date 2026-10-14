# Hướng dẫn xuất pack GNaviAlerts

Thư mục `maps-build` xuất dữ liệu bản đồ offline cho app.

Làm việc **trong thư mục gốc** (nơi có `tools/`, `vietnam.osm.pbf`, `hoangsa_truongsa.pbf`). Mọi lệnh bên dưới dùng đường dẫn tương đối.

---

## 1. Tải dữ liệu OSM nguồn

Cần hai file PBF đặt cạnh thư mục `tools/`:


| File                   | Nội dung                      | Nguồn tải                                                                                                                                |
| ---------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `vietnam.osm.pbf`      | Lục địa + đảo ven bờ Việt Nam | [Geofabrik — Vietnam](https://download.geofabrik.de/asia/vietnam.html) → tải **vietnam-latest.osm.pbf**, đổi tên thành `vietnam.osm.pbf` |
| `hoangsa_truongsa.pbf` | Bổ sung Hoàng Sa / Trường Sa  | Tự extract trên [BBBike extracts](https://extract.bbbike.org/?lang=en) (xem mục dưới)                                                    |




### Extract Hoàng Sa – Trường Sa trên BBBike

1. Mở [https://extract.bbbike.org/?lang=en](https://extract.bbbike.org/?lang=en)
2. Zoom / vẽ vùng bao quanh **Hoàng Sa** và **Trường Sa** (khung lon `110.5–117.5`, lat `7.0–17.8`)
3. **Format:** chọn **Protocol Buffer (PBF)**
4. Đặt tên vùng (ví dụ `hoangsa_truongsa`), nhập email → tạo extract
5. Khi nhận link tải, lưu file và đặt tên `hoangsa_truongsa.pbf` vào thư mục gốc `maps-build`

> Geofabrik Vietnam thường **không** đủ Hoàng Sa / Trường Sa theo cách app cần — vì vậy vùng Biển Đông lấy riêng từ BBBike rồi ghép bằng `--also hoangsa_truongsa.pbf`.

---



## 2. Cần cài gì

**Python (khuyến nghị)**

- Python 3.9+
- `pip install -r tools\requirements.txt`
- RAM: bbox nhỏ vài trăm MB; cả nước `.rmap` ~2 GB+

**Hoặc Docker**

```bat
docker build -t gnavi-extract ./tools
```

Cấu trúc source trong `tools/` (chi tiết: `tools\README.md`):


| Thư mục    | Việc                                     |
| ---------- | ---------------------------------------- |
| `lib/`     | Helper chung (tỉnh, vùng, tên OSM, args) |
| `regions/` | Xuất `regions.db`                        |
| `roads/`   | Xuất `roads_name.db` + `.rmap`           |
| `routing/` | Xuất routing tiles / meta                |
| `search/`  | Xuất `search.bin` GNS3                   |


Lệnh dưới vẫn dùng `tools\regions.py` … — đó là CLI mỏng trỏ vào từng thư mục trên.

---



## 3. Bốn lệnh xuất

Xuất vào thư mục output mới (ví dụ `out`). Luôn thêm `--also hoangsa_truongsa.pbf` nếu cần vùng Biển Đông.

Bước **routing** (`--tiles`) tự sinh metagraph trong folder vùng.

### Cả nước

```bat
python tools\regions.py vietnam.osm.pbf out\alert_data\regions.db
python tools\roads.py vietnam.osm.pbf out --mode both --also hoangsa_truongsa.pbf
python tools\routing.py vietnam.osm.pbf out --mode regions --tiles --also hoangsa_truongsa.pbf
python tools\search.py vietnam.osm.pbf out\alert_data\search.bin --also hoangsa_truongsa.pbf
```



### Theo tỉnh

```bat
# Git bash
set PROV=Nghe An,Ha Tinh,Quang Tri,Hue,Đa Nang,Quang Ngai
python tools\regions.py vietnam.osm.pbf out\alert_data\regions.db --provinces "%PROV%"
python tools\roads.py vietnam.osm.pbf out --provinces "%PROV%"
python tools\routing.py vietnam.osm.pbf out --provinces "%PROV%" --tiles
python tools\search.py vietnam.osm.pbf out\alert_data\search.bin --provinces "%PROV%"

# hoặc

# Powershell
$PROV="Nghe An,Ha Tinh,Quang Tri,Hue,Đa Nang,Quang Ngai"
python tools\regions.py vietnam.osm.pbf out\alert_data\regions.db --provinces $PROV
python tools\roads.py vietnam.osm.pbf out --provinces $PROV
python tools\routing.py vietnam.osm.pbf out --provinces $PROV --tiles
python tools\search.py vietnam.osm.pbf out\alert_data\search.bin --provinces $PROV
```

Pad `--provinces` mặc định cho `roads.py`: **0.12°**.

### Docker

```bat
docker run --rm -v "%cd%:/data" gnavi-extract ^
  /app/roads.py /data/vietnam.osm.pbf /data/out --mode both --also /data/hoangsa_truongsa.pbf
```

Đổi `/app/roads.py` thành `regions.py`, `routing.py` hoặc `search.py` cho ba lệnh còn lại. Tham số giống lệnh Python ở trên; đường dẫn file nằm trong `/data/`.

---



## 4. Kết quả

```
out/
  alert_data/
    regions.db
    roads_name.db
    search.bin
  roads_map/
    viet_nam/
    bien_dong/
      r_*.rmap
      routing.bin hoặc g_*.rbin + routing_index.bin
    ...
```

Cài lên xe bằng **Smart Sharing** (tab Bản đồ) trong G-Navi Pro.

### 7 thư mục vùng

1. `mien_nui_phia_bac`
2. `dong_bang_song_hong`
3. `bac_trung_bo`
4. `nam_trung_bo_tay_nguyen`
5. `dong_nam_bo`
6. `dong_bang_song_cuu_long`
7. `bien_dong` — Hoàng Sa / Trường Sa (từ `hoangsa_truongsa.pbf`)

