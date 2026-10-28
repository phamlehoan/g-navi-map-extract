#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OSM PBF -> roads_name.db + roads_map/*.rmap

  out_dir/
    roads_name.db
    roads_map/
      viet_nam/r_{cy}_{cx}.rmap   # hoặc 7 vùng (+ bien_dong)

Usage:
  python roads.py vietnam.osm.pbf out_pack --mode both --also hoangsa_truongsa.pbf
  python roads.py vietnam.osm.pbf out_pack --provinces "Ha Tinh,Da Nang,Quang Nam"
  python roads.py vietnam.osm.pbf out_dn --bbox 108.05,15.95,108.35,16.20
"""
from __future__ import print_function

import argparse
import json
import os
import sqlite3
import struct
import sys
import time

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from lib.common import add_common_args, ensure_osmium, resolve_bbox_and_pbfs
from lib.osm_names import place_name, road_name
from roads.rmap_format import (
    DEFAULT_SIMPLIFY_UNITS, SCALE, build_rmap, clip_polyline)
from routing.format import oneway_dir
from lib.vn_regions import REGIONS, VIET_NAM_ID, VIET_NAM_LABEL
from lib.vn_provinces import mainland_provinces

ensure_osmium()
import osmium  # noqa: E402

DEFAULT_CHUNK = 10000  # 0.1°
CHUNK_NODES = 40
CHUNK_OVERLAP = 1
FINE_CELL = 1000
# Pad mặc định khi --provinces (độ) — 0.05 quá sát biên, cắt QL/ĐT
DEFAULT_PROVINCE_PAD = 0.12

# vietnam = 1 thư mục viet_nam; regions = 7 vùng; both = viet_nam + 7 vùng;
# provinces = mỗi tỉnh/thành sau sáp nhập một thư mục snake_case (ha_noi, da_nang, …);
# all = viet_nam + 7 vùng + từng tỉnh
MODES = ("vietnam", "regions", "both", "provinces", "all")
# Đệm bbox tỉnh khi gán ô (độ): ô sát biên tỉnh vẫn nằm trong thư mục tỉnh, đường QL không bị cắt
PROVINCE_TILE_PAD = 0.05

INCLUDE_HIGHWAY = frozenset({
    "motorway", "motorway_link",
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
    "unclassified", "residential", "living_street",
    "service", "road",
    "track",
})
# Hẻm/đi bộ có tên — hay bị tag path/footway ở VN; chỉ lấy khi có name
INCLUDE_HIGHWAY_NAMED = frozenset({
    "path", "footway", "pedestrian", "cycleway", "steps",
})

# Đảo / đường bờ — cần cho vùng bien_dong (ít highway)
INCLUDE_NATURAL = frozenset(("coastline", "island", "islet", "reef"))
INCLUDE_PLACE = frozenset(("island", "islet", "archipelago"))

# tertiary trở lên — bản đồ nhẹ cho HU (KitKat)
HIGHWAY_HU_LIGHT = frozenset({
    "motorway", "motorway_link",
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
})

PACK_PROFILES = {
    "full": {
        "label": "Đầy đủ",
        "highways": INCLUDE_HIGHWAY,
    },
    "hu_light": {
        "label": "Nhẹ (HU / thẻ nhỏ)",
        "highways": HIGHWAY_HU_LIGHT,
    },
}


def regions_for_tile(cy, cx, chunk):
    lat = (cy * chunk + chunk * 0.5) / float(SCALE)
    lon = (cx * chunk + chunk * 0.5) / float(SCALE)
    hit = []
    for rid, _label, min_lon, min_lat, max_lon, max_lat in REGIONS:
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            hit.append(rid)
    if hit:
        return hit
    best = None
    best_d = 1e18
    for rid, _label, min_lon, min_lat, max_lon, max_lat in REGIONS:
        dlat = 0.0
        if lat < min_lat:
            dlat = min_lat - lat
        elif lat > max_lat:
            dlat = lat - max_lat
        dlon = 0.0
        if lon < min_lon:
            dlon = min_lon - lon
        elif lon > max_lon:
            dlon = lon - max_lon
        d = dlat * dlat + dlon * dlon
        if d < best_d:
            best_d = d
            best = rid
    return [best] if best else []


def provinces_for_tile(cy, cx, chunk):
    """Các tỉnh (bbox đệm PROVINCE_TILE_PAD) chứa tâm ô; ô ngoài mọi bbox (đảo xa) → tỉnh gần nhất."""
    lat = (cy * chunk + chunk * 0.5) / float(SCALE)
    lon = (cx * chunk + chunk * 0.5) / float(SCALE)
    hit = []
    best = None
    best_d = 1e18
    for p in mainland_provinces():
        min_lon, min_lat, max_lon, max_lat = p["bbox"]
        min_lon -= PROVINCE_TILE_PAD
        min_lat -= PROVINCE_TILE_PAD
        max_lon += PROVINCE_TILE_PAD
        max_lat += PROVINCE_TILE_PAD
        if min_lat <= lat <= max_lat and min_lon <= lon <= max_lon:
            hit.append(p["id"])
        dlat = max(min_lat - lat, 0.0, lat - max_lat)
        dlon = max(min_lon - lon, 0.0, lon - max_lon)
        d = dlat * dlat + dlon * dlon
        if d < best_d:
            best_d = d
            best = p["id"]
    if hit:
        return hit
    return [best] if best else []


def folder_ids_for_tile(cy, cx, chunk, mode):
    ids = []
    if mode in ("vietnam", "both", "all"):
        ids.append(VIET_NAM_ID)
    if mode in ("regions", "both", "all"):
        ids.extend(regions_for_tile(cy, cx, chunk))
    if mode in ("provinces", "all"):
        ids.extend(provinces_for_tile(cy, cx, chunk))
    seen = set()
    out = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def write_manifests(out_dir, chunk, mode):
    with open(os.path.join(out_dir, "manifest.txt"), "w", encoding="utf-8") as f:
        f.write("chunk_units=%d\n" % chunk)
        f.write("chunk_deg=%.4f\n" % (chunk / float(SCALE)))
        f.write("file=r_{cy}_{cx}.rmap\n")
        f.write("format=rmap\n")
        f.write("version=2\n")
        f.write("index=ridx\n")
        f.write("mode=%s\n" % mode)
        folders = []
        if mode in ("vietnam", "both", "all"):
            folders.append(VIET_NAM_ID)
        if mode in ("regions", "both", "all"):
            folders.extend(r[0] for r in REGIONS)
        if mode in ("provinces", "all"):
            folders.extend(p["id"] for p in mainland_provinces())
        f.write("folders=%s\n" % ",".join(folders))

    if mode in ("provinces", "all"):
        for p in mainland_provinces():
            d = os.path.join(out_dir, p["id"])
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "manifest.txt"), "w", encoding="utf-8") as f:
                f.write("chunk_units=%d\n" % chunk)
                f.write("file=r_{cy}_{cx}.rmap\n")
                f.write("format=rmap\n")
                f.write("region=%s\n" % p["id"])
                f.write("label=%s\n" % p["name"])
                f.write("bbox=%.4f,%.4f,%.4f,%.4f\n" % tuple(p["bbox"]))

    if mode in ("vietnam", "both", "all"):
        d = os.path.join(out_dir, VIET_NAM_ID)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "manifest.txt"), "w", encoding="utf-8") as f:
            f.write("chunk_units=%d\n" % chunk)
            f.write("file=r_{cy}_{cx}.rmap\n")
            f.write("format=rmap\n")
            f.write("region=%s\n" % VIET_NAM_ID)
            f.write("label=%s\n" % VIET_NAM_LABEL)

    if mode in ("regions", "both", "all"):
        for rid, label, *_bbox in REGIONS:
            d = os.path.join(out_dir, rid)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "manifest.txt"), "w", encoding="utf-8") as f:
                f.write("chunk_units=%d\n" % chunk)
                f.write("file=r_{cy}_{cx}.rmap\n")
                f.write("format=rmap\n")
                f.write("region=%s\n" % rid)
                f.write("label=%s\n" % label)


def pack_blob(pts_latlon_i):
    """Legacy coords_blob for roads_name.db (SpeedAlert)."""
    if len(pts_latlon_i) < 2:
        return None
    lats = [p[0] for p in pts_latlon_i]
    lons = [p[1] for p in pts_latlon_i]
    min_lat_i = min(lats)
    min_lon_i = min(lons)
    max_lat_i = max(lats)
    max_lon_i = max(lons)
    n = len(pts_latlon_i)
    buf = bytearray(2 + 4 + n * 8)
    buf[0] = ord("R")
    buf[1] = 1
    struct.pack_into("<I", buf, 2, n)
    off = 6
    for la, lo in pts_latlon_i:
        struct.pack_into("<ii", buf, off, lo - min_lon_i, la - min_lat_i)
        off += 8
    return min_lat_i, min_lon_i, max_lat_i, max_lon_i, bytes(buf)


class TileBucket(object):
    __slots__ = ("roads",)

    def __init__(self):
        # (name, [(lat_i, lon_i), ...], oneway) — oneway: 0 / 1 / -1 (giống routing)
        self.roads = []


class RoadHandler(osmium.SimpleHandler):
    def __init__(self, chunk, mode, bbox, named_rows, allowed_highways):
        super(RoadHandler, self).__init__()
        self.chunk = chunk
        self.mode = mode
        self.bbox = bbox
        self.named_rows = named_rows  # list for roads_name.db
        self.allowed_highways = allowed_highways or INCLUDE_HIGHWAY
        # key: (folder_id, cy, cx) -> TileBucket
        self.tiles = {}
        self.ways_seen = 0
        self.segments = 0
        self._t0 = time.time()
        self._last_log = self._t0

    def _in_bbox(self, lat, lon):
        if self.bbox is None:
            return True
        min_lon, min_lat, max_lon, max_lat = self.bbox
        return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon

    def _maybe_progress(self):
        now = time.time()
        if now - self._last_log < 15:
            return
        self._last_log = now
        print("... highways=%d segments=%d tiles=%d (%.0fs)" % (
            self.ways_seen, self.segments, len(self.tiles), now - self._t0), flush=True)

    def _add_segment(self, name, lat_i_list, lon_i_list, is_highway=True,
                     osm_way_id=0, oneway=0):
        n = len(lat_i_list)
        if n < 2:
            return
        pts = list(zip(lat_i_list, lon_i_list))
        # Đảo geometry khi oneway=-1 → điểm trong .rmap luôn theo chiều đi
        ow = int(oneway or 0)
        if ow < 0:
            pts = list(reversed(pts))
            ow = 1
        elif ow > 0:
            ow = 1
        min_la = min(p[0] for p in pts)
        max_la = max(p[0] for p in pts)
        min_lo = min(p[1] for p in pts)
        max_lo = max(p[1] for p in pts)

        # Only add to roads_name.db for actual highways (not natural/place features)
        if is_highway and name and len(name.strip()) >= 2:
            packed = pack_blob(pts)
            if packed:
                min_lat_i, min_lon_i, max_lat_i, max_lon_i, blob = packed
                # coordinates = JSON [[d_lon, d_lat],...] lệch so với min_lon/min_lat, đơn vị
                # 1e-5° (SỐ NGUYÊN) — khớp coords_blob và app (point = (min + d) / 1e5).
                # Bản trước ghi lệch theo ĐỘ (0.00312) → app/enhance cũ dồn mọi điểm về góc bbox.
                coords_json = json.dumps(
                    [[lo - min_lon_i, la - min_lat_i] for la, lo in pts],
                    separators=(",", ":"), ensure_ascii=False
                )
                self.named_rows.append(
                    (osm_way_id, name.strip(), min_lat_i, min_lon_i, max_lat_i, max_lon_i, coords_json, blob)
                )

        cy0 = min_la // self.chunk
        cy1 = max_la // self.chunk
        cx0 = min_lo // self.chunk
        cx1 = max_lo // self.chunk
        for cy in range(cy0, cy1 + 1):
            for cx in range(cx0, cx1 + 1):
                for folder_id in folder_ids_for_tile(cy, cx, self.chunk, self.mode):
                    key = (folder_id, cy, cx)
                    bucket = self.tiles.get(key)
                    if bucket is None:
                        bucket = TileBucket()
                        self.tiles[key] = bucket
                    bucket.roads.append((name, pts, ow))
        self.segments += 1

    def _way_label(self, tags):
        hw = tags.get("highway")
        if hw in self.allowed_highways:
            if tags.get("area") == "yes" or tags.get("indoor") == "yes":
                return None, False, False
            # Return name even if None/empty for main highways (to capture geometry)
            return road_name(tags), True, True
        if hw in INCLUDE_HIGHWAY_NAMED:
            if tags.get("area") == "yes" or tags.get("indoor") == "yes":
                return None, False, False
            nm = road_name(tags)
            if nm and len(nm.strip()) >= 2:
                return nm.strip(), True, True
            return None, False, False
        natural = tags.get("natural")
        if natural in INCLUDE_NATURAL:
            return place_name(tags), True, False
        if tags.get("place") in INCLUDE_PLACE:
            return place_name(tags), True, False
        return None, False, False

    def _clip_way_to_bbox(self, lats, lons):
        """Giữ phần polyline giao bbox (kể cả đoạn cắt góc — không cần node nằm trong)."""
        pts = [(int(round(la * SCALE)), int(round(lo * SCALE)))
               for la, lo in zip(lats, lons)]
        if self.bbox is None:
            return [pts] if len(pts) >= 2 else []
        min_lon, min_lat, max_lon, max_lat = self.bbox
        return clip_polyline(
            pts,
            int(round(min_lat * SCALE)),
            int(round(max_lat * SCALE)),
            int(round(min_lon * SCALE)),
            int(round(max_lon * SCALE)),
        )

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}
        name, ok, is_highway = self._way_label(tags)
        if not ok:
            return
        self.ways_seen += 1
        self._maybe_progress()

        lats = []
        lons = []
        for n in w.nodes:
            if not n.location.valid():
                continue
            lats.append(n.location.lat)
            lons.append(n.location.lon)
        if len(lats) < 2:
            return

# Cu: chi giu way neu co node trong bbox -> thieu duong cat goc tinh.
# Moi: clip polyline vao bbox (da pad) -- lay dung doan giao.
        polys = self._clip_way_to_bbox(lats, lons)
        if not polys:
            return

        ow = oneway_dir(tags) if is_highway else 0
        for pts in polys:
            i = 0
            n = len(pts)
            while i < n - 1:
                j = min(i + CHUNK_NODES, n)
                chunk = pts[i:j]
                la_i = [p[0] for p in chunk]
                lo_i = [p[1] for p in chunk]
                self._add_segment(name, la_i, lo_i, is_highway=is_highway,
                                  osm_way_id=w.id, oneway=ow)
                if j >= n:
                    break
                i = j - CHUNK_OVERLAP

    def node(self, n):
        """Dao/da chi co node (pho bien o Bien Dong) -> stub polyline + nhan VI."""
        tags = {t.k: t.v for t in n.tags}
        natural = tags.get("natural")
        place = tags.get("place")
        if natural not in INCLUDE_NATURAL and place not in INCLUDE_PLACE:
            return
        if not n.location.valid():
            return
        la = n.location.lat
        lo = n.location.lon
        if not self._in_bbox(la, lo):
            return
        name = place_name(tags)
        # stub ~40 m để vẽ được trên map
        d = 20  # SCALE units (SCALE=1e5 -> 0.0002°)
        la_i = int(round(la * SCALE))
        lo_i = int(round(lo * SCALE))
        self._add_segment(name, [la_i, la_i], [lo_i - d, lo_i + d], is_highway=False)
        self.ways_seen += 1


def write_named_db(path, rows):
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute(
        """CREATE TABLE roads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            osm_way_id INTEGER NOT NULL,
            name TEXT,
            minLat INTEGER,
            minLon INTEGER,
            maxLat INTEGER,
            maxLon INTEGER,
            coordinates TEXT,
            coords_blob BLOB
        )"""
    )
    batch = []
    n = 0
    for r in rows:
        batch.append(r)
        if len(batch) >= 2000:
            con.executemany(
                "INSERT INTO roads(osm_way_id,name,minLat,minLon,maxLat,maxLon,coordinates,coords_blob) "
                "VALUES (?,?,?,?,?,?,?,?)",
                batch,
            )
            n += len(batch)
            batch = []
            if n % 50000 == 0:
                print("... named rows=%d" % n, flush=True)
                con.commit()
    if batch:
        con.executemany(
            "INSERT INTO roads(osm_way_id,name,minLat,minLon,maxLat,maxLon,coordinates,coords_blob) "
            "VALUES (?,?,?,?,?,?,?,?)",
            batch,
        )
        n += len(batch)
    con.commit()

    # road_cells index
    con.execute(
        "CREATE TABLE road_cells ("
        "cell INTEGER NOT NULL,"
        "road_id INTEGER NOT NULL)"
    )
    cell_batch = []
    for r in con.execute("SELECT id, minLat, minLon, maxLat, maxLon FROM roads"):
        rid, min_la, min_lo, max_la, max_lo = r
        for cy in range(min_la // FINE_CELL, max_la // FINE_CELL + 1):
            for cx in range(min_lo // FINE_CELL, max_lo // FINE_CELL + 1):
                cell_batch.append((cy * 1_000_000 + cx, rid))
                if len(cell_batch) >= 50000:
                    con.executemany(
                        "INSERT INTO road_cells(cell, road_id) VALUES (?,?)", cell_batch
                    )
                    cell_batch = []
    if cell_batch:
        con.executemany(
            "INSERT INTO road_cells(cell, road_id) VALUES (?,?)", cell_batch
        )
    con.execute("CREATE INDEX idx_road_cells_cell ON road_cells(cell)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_roads_maxLat ON roads(maxLat)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_roads_minLat ON roads(minLat)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_roads_osm_way ON roads(osm_way_id)")
    # Composite index for bbox queries (matches SpeedAlertRepository.createBboxIndexesAsync)
    con.execute("CREATE INDEX IF NOT EXISTS idx_roads_name_bbox ON roads(maxLat, minLat, maxLon, minLon)")
    con.execute("ANALYZE")
    con.commit()
    con.close()
    return n


def flush_tiles(tiles, map_dir, chunk, simplify_units=DEFAULT_SIMPLIFY_UNITS, pad_units=None):
    n_files = 0
    n_roads = 0
    total_bytes = 0
    for (folder_id, cy, cx), bucket in tiles.items():
        data = build_rmap(cy, cx, chunk, bucket.roads, simplify_units=simplify_units,
                          pad_units=pad_units)
        if not data:
            continue
        d = os.path.join(map_dir, folder_id)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "r_%d_%d.rmap" % (cy, cx))
        with open(path, "wb") as f:
            f.write(data)
        n_files += 1
        # rough road count from header
        n_roads += struct.unpack_from("<I", data, 24)[0]
        total_bytes += len(data)
        if n_files % 200 == 0:
            print("... wrote %d rmap files" % n_files, flush=True)
    return n_files, n_roads, total_bytes


def main():
    ap = argparse.ArgumentParser(
        description="OSM PBF -> roads_map/*.rmap + roads_name.db")
    ap.add_argument("pbf", help="vietnam.osm.pbf")
    ap.add_argument("out_dir", help="Thư mục xuất (roads_name.db + roads_map/)")
    ap.add_argument("--mode", choices=MODES, default="vietnam",
                    help="vietnam | regions | both | provinces (mỗi tỉnh/thành sau sáp nhập một "
                         "thư mục snake_case) | all (mặc định vietnam; "
                         "khi --provinces tự dùng vietnam)")
    ap.add_argument("--chunk", type=int, default=DEFAULT_CHUNK)
    ap.add_argument("--simplify", type=int, default=DEFAULT_SIMPLIFY_UNITS,
                    help="Douglas-Peucker (đơn vị 1e-5° ≈ 1.1m, mặc định %d; 0 = tắt). "
                         "Giữ nguyên nút giao giữa các đường." % DEFAULT_SIMPLIFY_UNITS)
    ap.add_argument("--tile-pad", type=int, default=None,
                    help="Vùng đệm quanh mỗi tile .rmap (đơn vị 1e-5°). Mặc định ±2000 "
                         "(tương thích app cũ). App mới (chọn tile theo bbox) dùng 0 → "
                         "tile nhẹ hơn nhiều.")
    ap.add_argument("--skip-name", action="store_true",
                    help="Không ghi roads_name.db")
    ap.add_argument("--pack-profile", choices=sorted(PACK_PROFILES.keys()),
                    default="full",
                    help="full=đủ kiệt/residential; hu_light=QL/ĐT/tỉnh lộ (nhẹ HU)")
    add_common_args(ap)
    # Pad rộng hơn khi xuất theo tỉnh (tránh cắt QL sát biên)
    for a in ap._actions:
        if a.dest == "pad":
            a.default = DEFAULT_PROVINCE_PAD
            break
    args = ap.parse_args()

    bbox, pbfs, provinces = resolve_bbox_and_pbfs(args)
    # Pack theo tinh -> 1 folder viet_nam (nhe, du cho Smart Sharing)
    mode = args.mode
    if provinces and mode != "vietnam":
        print("==> --provinces -> mode=vietnam (1 folder viet_nam)", flush=True)
        mode = "vietnam"

    os.makedirs(args.out_dir, exist_ok=True)
    map_dir = os.path.join(args.out_dir, "roads_map")
    if os.path.isdir(map_dir):
        # chỉ xóa thư mục xuất của lần chạy này, không đụng pack cũ ngoài out_dir
        import shutil
        shutil.rmtree(map_dir)
    os.makedirs(map_dir)
    write_manifests(map_dir, args.chunk, mode)

    named_rows = []
    t0 = time.time()
    profile = PACK_PROFILES[args.pack_profile]
    print("==> mode=%s profile=%s chunk=%d -> %s" % (
        mode, args.pack_profile, args.chunk, args.out_dir), flush=True)

    h = RoadHandler(args.chunk, mode, bbox, named_rows, profile["highways"])
    for pbf in pbfs:
        print("==> Scanning", pbf, flush=True)
        h.apply_file(pbf, locations=True)
    print("==> Ways highway=%d segments=%d tile-buckets=%d" % (
        h.ways_seen, h.segments, len(h.tiles)), flush=True)

    print("==> Writing .rmap tiles…", flush=True)
    n_files, n_roads, nbytes = flush_tiles(h.tiles, map_dir, args.chunk, args.simplify,
                                           args.tile_pad)
    print("==> rmap files=%d road-copies=%d size=%.1f MB" % (
        n_files, n_roads, nbytes / (1024 * 1024.0)), flush=True)

    if not args.skip_name:
        alert_dir = os.path.join(args.out_dir, "alert_data")
        os.makedirs(alert_dir, exist_ok=True)
        name_path = os.path.join(alert_dir, "roads_name.db")
        print("==> roads_name.db (%d candidates)…" % len(named_rows), flush=True)
        n_named = write_named_db(name_path, named_rows)
        sz = os.path.getsize(name_path) / (1024 * 1024.0)
        print("==> named rows=%d size=%.1f MB" % (n_named, sz), flush=True)

    print("==> Done in %.1fs -> %s" % (time.time() - t0, args.out_dir), flush=True)
    print("    Smart Sharing -> tab Ban do -> upload roads_map/ + alert_data/roads_name.db",
          flush=True)


if __name__ == "__main__":
    main()
