# tools/ — nguồn xuất pack bản đồ GNavi

Làm việc từ thư mục gốc `maps-build` (cạnh `vietnam.osm.pbf`).  
Chi tiết lệnh: xem `../HUONG_DAN.md`.

## Cấu trúc

```
tools/
  regions.py / roads.py / routing.py / search.py   ← CLI mỏng (giữ path cũ)
  requirements.txt
  Dockerfile

  lib/          Shared: args CLI, tên OSM, tỉnh/vùng VN
  regions/      Xuất regions.db (phường / tỉnh)
  roads/        Xuất roads_name.db + roads_map/*.rmap
  routing/      Xuất routing tiles, meta, ALT accel
  search/       Xuất search.bin (GNS3 offline geocoder)
```

| Thư mục / file | Mục đích |
|----------------|----------|
| **lib/common.py** | `--bbox`, `--provinces`, `--also`, kiểm tra osmium |
| **lib/osm_names.py** | Lấy tên đường / địa danh từ tag OSM |
| **lib/vn_provinces.py** | Danh sách tỉnh, map tỉnh cũ→mới, bbox |
| **lib/vn_regions.py** | 7 vùng `roads_map` (+ `bien_dong`) |
| **regions/build.py** | OSM → `regions.db` |
| **roads/build.py** | OSM → `roads_name.db` + `.rmap` |
| **roads/rmap_format.py** | Binary format RMAP |
| **routing/build.py** | OSM → `g_*.rbin` / `routing.bin` |
| **routing/format.py** | Binary format GNR1 |
| **routing/tiles.py** | Cắt đồ thị theo ô |
| **routing/meta.py** | Gom skeleton → `routing_meta.bin` |
| **routing/accel.py** | ALT landmarks từ meta |
| **search/build.py** | OSM → `search.bin` |
| **search/format_gns3.py** | Format GNS3 (app OfflineGeocoder) |
| **search/format_legacy.py** | Format GNS1 cũ (không dùng cho app hiện tại) |

## Chạy

Giữ nguyên path cũ (khuyến nghị):

```bat
python tools\regions.py ...
python tools\roads.py ...
python tools\routing.py ...
python tools\search.py ...
```

Hoặc gọi thẳng module (cần `tools` trên `PYTHONPATH`):

```bat
set PYTHONPATH=tools
python -m regions.build ...
python -m roads.build ...
python -m routing.build ...
python -m search.build ...
```

Routing phụ trợ (thường `routing.py --tiles` gọi sẵn):

```bat
set PYTHONPATH=tools
python -m routing.meta path\to\region_dir
python -m routing.accel path\to\region_dir
```
