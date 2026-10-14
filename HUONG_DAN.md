# Hướng dẫn xuất pack GNaviAlerts

Thư mục `build-script` xuất dữ liệu bản đồ offline cho app.

Làm việc **trong thư mục gốc** (nơi có `tools/`, `data_source/`, `vietnam.osm.pbf`, `hoangsa_truongsa.osm.pbf`). Mọi lệnh bên dưới dùng đường dẫn tương đối.

---

## 1. Cấu trúc dữ liệu nguồn

```
build-script/
├── data_source/                  # Dữ liệu riêng (không commit git)
│   ├── vietnam.osm.pbf           # OSM toàn quốc (Geofabrik)
│   ├── hoangsa_truongsa.osm.pbf  # Bổ sung Hoàng Sa / Trường Sa (BBBike)
│   ├── speed_limit.db            # Giới hạn tốc độ (data riêng)
│   └── spds.db                   # Camera/biển báo (data riêng)
├── tools/                        # Scripts xuất dữ liệu
├── out/                          # Thư mục xuất (gitignored)
└── analyze/                      # Scratchpad AI (gitignored)
```

### 1.1 Tải dữ liệu OSM nguồn

Cần hai file PBF đặt trong `data_source/`:

| File | Nội dung | Nguồn tải |
|------|----------|-----------|
| `vietnam.osm.pbf` | Lục địa + đảo ven bờ Việt Nam | [Geofabrik — Vietnam](https://download.geofabrik.de/asia/vietnam.html) → tải **vietnam-latest.osm.pbf**, đổi tên thành `vietnam.osm.pbf` |
| `hoangsa_truongsa.osm.pbf` | Bổ sung Hoàng Sa / Trường Sa | Tự extract trên [BBBike extracts](https://extract.bbbike.org/?lang=en) |

### 1.2 Extract Hoàng Sa – Trường Sa trên BBBike

1. Mở [https://extract.bbbike.org/?lang=en](https://extract.bbbike.org/?lang=en)
2. Zoom / vẽ vùng bao quanh **Hoàng Sa** và **Trường Sa** (khung lon `110.5–117.5`, lat `7.0–17.8`)
3. **Format:** chọn **Protocol Buffer (PBF)**
4. Đặt tên vùng (ví dụ `hoangsa_truongsa`), nhập email → tạo extract
5. Khi nhận link tải, lưu file và đặt tên `hoangsa_truongsa.osm.pbf` vào `data_source/`

> Geofabrik Vietnam thường **không** đủ Hoàng Sa / Trường Sa theo cách app cần — vì vậy vùng Biển Đông lấy riêng từ BBBike rồi ghép bằng `--also data_source/hoangsa_truongsa.osm.pbf`.

### 1.3 Dữ liệu riêng (chỉ speed_limit, spds)

Hai file DB này là dữ liệu riêng tự thu thập, **không xuất từ OSM**. Cần chuẩn bị sẵn và đặt vào `data_source/`. Sau đó chạy script enhancement để bổ sung index và liên kết, **xuất trực tiếp ra `out/alert_data/`**:

```bat
# 1. Xuất roads_name.db từ OSM (cần trước để match tên đường)
python tools\roads.py data_source\vietnam.osm.pbf out --mode vietnam --also data_source\hoangsa_truongsa.osm.pbf

# 2. Enhance spds.db: thêm grid index cho camera/biển
python tools\enhance_spds.py data_source\spds.db out\alert_data\spds.db

# 3. Enhance speed_limit.db: match đoạn tốc độ → đường có tên (road_name_id) + bảng speed_cells
#    BẮT BUỘC chạy lại MỖI LẦN xuất roads_name.db (id AUTOINCREMENT đổi mỗi lần xuất),
#    và chép speed_limit.db + roads_name.db lên máy CÙNG LÚC.
python tools\enhance_speed_limit.py data_source\speed_limit.db out\alert_data\roads_name.db out\alert_data\speed_limit.db

# 4. names.pack (tra tên đường nhanh) — cạnh roads_name.db
python tools\names_pack.py out\alert_data\roads_name.db
```

> **Thứ tự:** nên chạy bước 2 (spds) TRƯỚC bước 3 — bước 3 đọc `spds.db` và `regions.db`
> nằm CẠNH `roads_name.db` để suy tốc độ từ biển báo.

### 1.3.1 File pack nhị phân (app đọc bằng mmap — nhanh, ít RAM)

| File | Tạo bởi | Thay cho |
|------|---------|----------|
| `speed.pack` | `enhance_speed_limit.py` (tự tạo cạnh `speed_limit.db` đầu ra) | SQL + JSON khi tra tốc độ mỗi tick GPS |
| `names.pack` | `names_pack.py` | SQL `road_cells` khi tra tên đường |

**Vẫn phải chép cả `speed_limit.db` và `roads_name.db`:** app chỉ mở `names.pack` khi có
`roads_name.db`, và vẫn dùng 2 DB này để tra theo id / `osm_way_id`, giữ đường đang đi và
làm dự phòng khi pack thiếu/hỏng. Pack chỉ thay phần tra cứu "nóng". Cả 4 file phải sinh từ
CÙNG một lần xuất `roads_name.db` và chép lên máy cùng lúc.

### 1.3.2 Tốc độ suy ra (`infer_speed.py`, tự chạy trong `enhance_speed_limit.py`)

Đường CÓ TÊN chưa khớp đoạn nào trong `speed_limit.db` được gán tốc độ. Chỉ ghi vào
`speed.pack` (byte nguồn: 0 = dữ liệu gốc, 1 = theo luật, 2 = theo biển):

1. **Biển báo** (`spds.db`, t=1): biển cách đường ≤25 m, cùng phương (±30°), chiều theo hướng biển.
2. **Luật** (Thông tư 38/2024/TT-BGTVT, mức đường 2 chiều/1 làn vì không biết số làn):
   - trong khu đông dân cư **50**, ngoài khu đông dân cư **80**;
   - khu dân cư = Phường/Thị trấn (`regions.db`); trong Xã/Đặc khu chỉ QL/ĐT/TL tính là
     ngoài khu dân cư, đường tên khác tính là trong khu dân cư;
   - bỏ qua đường "Cao tốc".

Trên app: dữ liệu gốc luôn được ưu tiên; số tốc độ theo **luật** hiện **mờ**; biển ở gần
vẫn ghi đè. Tắt bước này bằng `--no-infer`; đổi file nguồn bằng `--spds <path>` / `--regions <path>`.

### 1.4 Đèn giao thông (traffic_lights) - xuất từ OSM

```bat
python tools\traffic_lights.py data_source\vietnam.osm.pbf out\alert_data\traffic_lights.db --also data_source\hoangsa_truongsa.osm.pbf
```

Trích xuất: `highway=traffic_signals`, `highway=crossing + crossing=traffic_signals`, `railway=level_crossing`.

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

| Thư mục | Việc |
|---------|------|
| `lib/` | Helper chung (tỉnh, vùng, tên OSM, args) |
| `regions/` | Xuất `regions.db` |
| `roads/` | Xuất `roads_name.db` + `.rmap` |
| `routing/` | Xuất routing tiles / meta |
| `search/` | Xuất `search.bin` GNS3 |
| `traffic_lights.py` | Xuất `traffic_lights.db` từ OSM |
| `enhance_speed_limit.py` | Enhance `speed_limit.db` (match geometry + name) |
| `enhance_spds.py` | Enhance `spds.db` (grid index) |
| `infer_speed.py` | Suy tốc độ (biển + luật) — module của `enhance_speed_limit.py` |
| `names_pack.py` | Xuất `names.pack` từ `roads_name.db` |

Lệnh dưới vẫn dùng `tools\regions.py` … — đó là CLI mỏng trỏ vào từng thư mục trên.

---

## 3. Quy trình xuất hoàn chỉnh (Cả nước)

```bat
=== 1. Xuất OSM-based data ===
# Lưu ý: có thể bỏ "--also data_source\hoangsa_truongsa.osm.pbf" để xuất nhanh hơn nếu bạn không lái xe ở Hoàng Sa và Trường Sa :)
# Tác giả khẳng định chủ quyền thiêng liêng của tổ quốc. Hoàng Sa và Trường Sa là chủ quyền của Việt Nam!

python tools\regions.py data_source\vietnam.osm.pbf out\alert_data\regions.db --also data_source\hoangsa_truongsa.osm.pbf
python tools\roads.py data_source\vietnam.osm.pbf out --mode both --also data_source\hoangsa_truongsa.osm.pbf
python tools\routing.py data_source\vietnam.osm.pbf out --mode regions --tiles --also data_source\hoangsa_truongsa.osm.pbf
python tools\search.py data_source\vietnam.osm.pbf out\alert_data\search.bin --also data_source\hoangsa_truongsa.osm.pbf
python tools\traffic_lights.py data_source\vietnam.osm.pbf out\alert_data\traffic_lights.db --also data_source\hoangsa_truongsa.osm.pbf

=== 2. Enhance DB riêng (cần roads_name.db đã xuất) - xuất thẳng ra out/alert_data/ ===
python tools\enhance_speed_limit.py data_source\speed_limit.db out\alert_data\roads_name.db out\alert_data\speed_limit.db
python tools\enhance_spds.py data_source\spds.db out\alert_data\spds.db
```

### Theo tỉnh

```bat
# Git bash
# Lưu ý: có thể bỏ "--also data_source\hoangsa_truongsa.osm.pbf" để xuất nhanh hơn nếu bạn không lái xe ở Hoàng Sa và Trường Sa :)
# Tác giả khẳng định chủ quyền thiêng liêng của tổ quốc. Hoàng Sa và Trường Sa là chủ quyền của Việt Nam!

set PROV=Nghe An,Ha Tinh,Quang Tri,Hue,Đa Nang,Quang Ngai
python tools\regions.py data_source\vietnam.osm.pbf out\alert_data\regions.db --provinces "%PROV%" --also data_source\hoangsa_truongsa.osm.pbf
python tools\roads.py data_source\vietnam.osm.pbf out --provinces "%PROV%" --also data_source\hoangsa_truongsa.osm.pbf
python tools\routing.py data_source\vietnam.osm.pbf out --provinces "%PROV%" --tiles --also data_source\hoangsa_truongsa.osm.pbf
python tools\search.py data_source\vietnam.osm.pbf out\alert_data\search.bin --provinces "%PROV%" --also data_source\hoangsa_truongsa.osm.pbf
python tools\traffic_lights.py data_source\vietnam.osm.pbf out\alert_data\traffic_lights.db --provinces "%PROV%" --also data_source\hoangsa_truongsa.osm.pbf

# Enhance DB riêng (giống cả nước) - xuất thẳng ra out/alert_data/
python tools\enhance_speed_limit.py data_source\speed_limit.db out\alert_data\roads_name.db out\alert_data\speed_limit.db
python tools\enhance_spds.py data_source\spds.db out\alert_data\spds.db
```

Pad `--provinces` mặc định cho `roads.py`: **0.12°**.

Tuỳ chọn thêm của `roads.py`:

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `--simplify N` | `2` (~2m) | Douglas-Peucker cho `.rmap` (giữ nguyên nút giao). `0` = tắt |
| `--tile-pad N` | ±2000 (0.02°) | Vùng đệm quanh mỗi tile `.rmap`. App bản mới chọn tile theo bbox → dùng `--tile-pad 0` cho tile nhẹ hơn. App cũ (cửa sổ 5 ô) cần giữ mặc định |

### Docker

```bat
docker run --rm -v "%cd%:/data" gnavi-extract ^
  /app/roads.py /data/data_source/vietnam.osm.pbf /data/out --mode both --also /data/data_source/hoangsa_truongsa.osm.pbf
```

Đổi `/app/roads.py` thành `regions.py`, `routing.py`, `search.py`, `traffic_lights.py` hoặc `enhance_speed_limit.py` cho các lệnh còn lại. Tham số giống lệnh Python ở trên; đường dẫn file nằm trong `/data/`.

---

## 4. Kết quả

```
out/
  alert_data/
    regions.db
    roads_name.db
    search.bin
    speed_limit.db        # enhanced: road_name_id, highway_class, name_hash, speed_cells
    spds.db               # enhanced: sign_cells grid index + idx_spds_yx
    traffic_lights.db     # from OSM: light_cells grid index
  roads_map/
    viet_nam/
    bien_dong/
      r_*.rmap
      routing.bin hoặc g_*.rbin + routing_index.bin
    ...
```

Cài lên xe bằng **Smart Sharing** (tab Bản đồ) trong G-Navi Pro hoặc copy trực tiếp các files output. trong 2 thư mục "alert_data" và "roads_map" trong thư mục "GNaviAlerts" đã được cấp quyền trong app (Vui lòng vào mục Cài đặt/Cấp quyền ghi bộ nhớ trong G-Navi Pro để kiểm tra thư mục đã chỉ định nơi chứa dữ liệu).

### 7 thư mục vùng routing

1. `mien_nui_phia_bac`
2. `dong_bang_song_hong`
3. `bac_trung_bo`
4. `nam_trung_bo_tay_nguyen`
5. `dong_nam_bo`
6. `dong_bang_song_cuu_long`
7. `bien_dong` - Hoàng Sa / Trường Sa

---

## 5. Tối ưu hóa query (tóm tắt kỹ thuật)

### Schema enhancements đã áp dụng:

| DB | Bảng | Cột mới | Index mới | Lợi ích |
|----|------|---------|-----------|---------|
| `speed_limit.db` | `roads` + `speed_cells(cell, road_id)` | `road_name_id` (FK → roads_name.id, match hình học + hướng, ~84%), `osm_way_id` (nếu roads_name có), `highway_class`, `name_hash`, `minLat`…`maxLon` | `idx_speed_cells(cell, road_id)` (covering), `idx_speed_road_name`, `idx_speed_osm_way` | App tra theo ô 0.01° (khoá `latCell*100000+lonCell`, khớp `SpeedRowIndex.java`) thay vì full-scan 220k dòng (~1.5s → vài ms trên Head  Unit|
| `spds.db` | `spds` | `lat_i`, `lon_i` (int 1e7) | `sign_cells(cell, sign_id)`, `idx_sign_cells_cell` | Query camera/biển theo grid 100m thay vì full scan |
| `traffic_lights.db` | `traffic_lights` | `lat_i`, `lon_i` | `light_cells(cell, light_id)` | Query đèn giao thông theo grid |
| `regions.db` | `wards` | `admin_level` (OSM VN hiện tại: xã/phường mới = 6) | `idx_wards_bbox(max_lat, min_lat, max_lon, min_lon)` | Mỗi mảnh (outer ring) của phường = 1 dòng; cấp cao ghi trước, mảnh lớn ghi sau (app lấy polygon đầu tiên chứa điểm, cache theo tên) |
| `roads_name.db` | `roads` | `osm_way_id` (stable OSM ID) | `idx_roads_name_bbox(maxLat, minLat, maxLon, minLon)` | Bbox query tên đường nhanh; lookup bằng OSM ID ổn định |

### Tác động performance (ước tính):

- **speed_limit**: Giảm ~3-5 query/tick → ~1 query (chỉ bbox + class filter)
- **spds/traffic_lights**: Grid index O(1) cell lookup thay vì O(N) scan
- **regions/roads_name**: Composite bbox index dùng được index seek

### Định dạng cần nhớ

- `roads_name.db.coordinates` = JSON `[[dLon, dLat], …]`, lệch so với `minLon/minLat`, **đơn vị 1e-5° (số nguyên)**. Pack cũ (lệch theo độ, số thập phân) app và `enhance_speed_limit.py` vẫn tự nhận.
- Routing (`routing.py`): mọi node OSM là đỉnh graph — app snap GPS vào **node** gần nhất, không nén graph.

---

## 6. Ghi chú cho AI agents

- Mọi code test/phân tích ghi vào `analyze/` (đã gitignore)
- Không commit file trong `data_source/` (chứa data riêng)
- Enhanced DB xuất thẳng ra `out/alert_data/` (không qua `data_source/enhanced_*`)
- Xem `AGENTS.md` cho quy tắc scratchpad