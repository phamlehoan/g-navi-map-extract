#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhance speed_limit.db cho app (HU Android 4.4):

  1. Gắn mỗi đoạn tốc độ với ĐƯỜNG CÓ TÊN tương ứng trong roads_name.db
     -> road_name_id, osm_way_id (nếu roads_name có), name_hash.
  2. Bảng speed_cells(cell, road_id) + index -> app tra theo ô 0.01° thay vì
     full-scan 220k dòng (~1.5s/lần trên HU). Cùng khoá ô với SpeedRowIndex.java.
  3. highway_class (heuristic theo tốc độ) + bbox int 1e5 (giữ tương thích).

Thuật toán match (bản cũ chỉ khớp 0.2%):
  - Lấy mẫu dọc đoạn tốc độ ~SAMPLE_STEP_M một điểm (tối đa MAX_SAMPLES).
  - Mỗi mẫu: đoạn đường-tên gần nhất trong MATCH_RADIUS_M VÀ cùng phương
    (lệch ≤ MAX_HEADING_DIFF, không xét chiều) -> 1 phiếu cho đường đó.
  - Đường nhiều phiếu nhất thắng nếu ≥ MIN_VOTE_RATIO số mẫu.
  Lọc hướng để đoạn nằm SÁT ngã tư không bị gán sang đường cắt ngang.

roads_name.db: coordinates = JSON [[dLon, dLat], ...], dLon/dLat là ĐỘ lệch so
với minLon/minLat (int 1e5). Bản cũ chia cả độ lệch cho 1e5 -> mọi điểm dồn về
góc bbox -> gần như không match.

Usage:
  python enhance_speed_limit.py data_source/speed_limit.db out/alert_data/roads_name.db out/alert_data/speed_limit.db
"""
from __future__ import print_function

import argparse
import json
import struct
import math
import os
import shutil
import sqlite3
import sys
import time
from array import array

try:
    import mmh3
except ImportError:  # name_hash chỉ là phụ — thiếu mmh3 vẫn chạy được
    mmh3 = None

SCALE = 100000
M_PER_DEG = 111320.0

MATCH_RADIUS_M = 20.0
MAX_HEADING_DIFF = 30.0
SAMPLE_STEP_M = 15.0
MAX_SAMPLES = 16
MIN_VOTE_RATIO = 0.5

# Lưới đoạn đường-tên khi match (~55m)
SEG_CELL_DEG = 0.0005
# Ô cho bảng speed_cells — PHẢI khớp SpeedRowIndex.CELL_DEG / KEY_MUL trong app
APP_CELL_DEG = 0.01
APP_KEY_MUL = 100000


def name_hash(name):
    if not name or mmh3 is None:
        return 0
    return mmh3.hash(name.lower().strip(), seed=42, signed=True)


def highway_class_from_speed(fwd, rev):
    s = max(fwd or 0, rev or 0)
    if s >= 100:
        return 1
    if s >= 80:
        return 2
    if s >= 60:
        return 3
    if s >= 50:
        return 4
    if s >= 40:
        return 5
    return 6


def seg_key(lat, lon):
    return (int(math.floor(lat / SEG_CELL_DEG)) << 32) | (int(math.floor(lon / SEG_CELL_DEG)) & 0xffffffff)


def app_cell(deg):
    return int(math.floor(deg / APP_CELL_DEG))


def build_named_index(path):
    """roads_name.db → (segs, names, osm, has_osm). segs = mảng nguyên thủy + lưới CSR."""
    t0 = time.time()
    con = sqlite3.connect(path)
    cols = [r[1] for r in con.execute("PRAGMA table_info(roads)")]
    has_osm = 'osm_way_id' in cols
    sql = ("SELECT id, name, minLat, minLon, coordinates"
           + (", osm_way_id" if has_osm else "")
           + " FROM roads WHERE name IS NOT NULL AND length(name) > 1")
    alat, alon, blat, blon = array('d'), array('d'), array('d'), array('d')
    rids = array('l')
    names = {}
    osm = {}
    cell_keys = array('q')
    cell_segs = array('l')
    pad = MATCH_RADIUS_M / M_PER_DEG
    n_roads = 0
    for row in con.execute(sql):
        rid, name, min_lat_i, min_lon_i, coords = row[:5]
        try:
            arr = json.loads(coords)
        except Exception:
            continue
        if len(arr) < 2:
            continue
        # Delta theo ĐỘ (builder hiện tại) hay đơn vị 1e-5 (pack cũ, số nguyên)
        deg = any(p[0] != int(p[0]) or p[1] != int(p[1]) for p in arr if len(p) >= 2)
        div = 1.0 if deg else float(SCALE)
        base_lat = min_lat_i / float(SCALE)
        base_lon = min_lon_i / float(SCALE)
        names[rid] = name.strip()
        if has_osm and row[5]:
            osm[rid] = row[5]
        n_roads += 1
        prev = None
        for p in arr:
            if len(p) < 2:
                continue
            cur = (base_lat + p[1] / div, base_lon + p[0] / div)
            if prev is not None and cur != prev:
                la1, lo1 = prev
                la2, lo2 = cur
                s = len(rids)
                alat.append(la1)
                alon.append(lo1)
                blat.append(la2)
                blon.append(lo2)
                rids.append(rid)
                # Ghi đoạn vào mọi ô của bbox(đoạn)+bán kính → khi tra chỉ cần đúng 1 ô
                padlon = pad / max(math.cos(math.radians(la1)), 1e-6)
                y0 = int(math.floor((min(la1, la2) - pad) / SEG_CELL_DEG))
                y1 = int(math.floor((max(la1, la2) + pad) / SEG_CELL_DEG))
                x0 = int(math.floor((min(lo1, lo2) - padlon) / SEG_CELL_DEG))
                x1 = int(math.floor((max(lo1, lo2) + padlon) / SEG_CELL_DEG))
                for y in range(y0, y1 + 1):
                    for x in range(x0, x1 + 1):
                        cell_keys.append((y << 32) | (x & 0xffffffff))
                        cell_segs.append(s)
            prev = cur
    con.close()
    print("    named roads=%d segments=%d cell-entries=%d (%.0fs)" % (
        n_roads, len(rids), len(cell_keys), time.time() - t0), flush=True)

    # CSR theo cell
    t1 = time.time()
    order = sorted(range(len(cell_keys)), key=cell_keys.__getitem__)
    seg_order = array('l', (cell_segs[i] for i in order))
    cells = {}
    n = len(order)
    start = 0
    while start < n:
        k = cell_keys[order[start]]
        end = start + 1
        while end < n and cell_keys[order[end]] == k:
            end += 1
        cells[k] = (start, end)
        start = end
    del order, cell_keys, cell_segs
    print("    grid cells=%d (%.0fs)" % (len(cells), time.time() - t1), flush=True)
    return (alat, alon, blat, blon, rids, seg_order, cells), names, osm, has_osm


def _axis(dx, dy):
    """Phương 0..180° (không xét chiều) của vector (dx đông, dy bắc)."""
    return math.degrees(math.atan2(dx, dy)) % 180.0


def _axis_diff(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def match_segment(pts, segs):
    """pts: [(lat, lon)] của đoạn tốc độ → (road_id | None, votes, samples)."""
    alat, alon, blat, blon, rids, seg_order, cells = segs

    # Lấy mẫu đều dọc polyline (theo mét)
    lens = []
    total = 0.0
    for i in range(len(pts) - 1):
        la1, lo1 = pts[i]
        la2, lo2 = pts[i + 1]
        dy = (la2 - la1) * M_PER_DEG
        dx = (lo2 - lo1) * M_PER_DEG * math.cos(math.radians(la1))
        L = math.hypot(dx, dy)
        lens.append((L, _axis(dx, dy)))
        total += L
    if total <= 0:
        return None, 0, 0
    n_samp = max(1, min(MAX_SAMPLES, int(total / SAMPLE_STEP_M)))
    step = total / n_samp
    target = step * 0.5
    acc = 0.0
    samples = []
    for i, (L, axis) in enumerate(lens):
        if L <= 0:
            continue
        la1, lo1 = pts[i]
        la2, lo2 = pts[i + 1]
        while target <= acc + L and len(samples) < n_samp:
            t = (target - acc) / L
            samples.append((la1 + (la2 - la1) * t, lo1 + (lo2 - lo1) * t, axis))
            target += step
        acc += L

    r2 = MATCH_RADIUS_M * MATCH_RADIUS_M
    votes = {}
    for slat, slon, axis in samples:
        rng = cells.get(seg_key(slat, slon))
        if rng is None:
            continue
        kx = M_PER_DEG * math.cos(math.radians(slat))
        best_d = r2
        best_r = None
        for j in range(rng[0], rng[1]):
            s = seg_order[j]
            # Hệ phẳng cục bộ (m), gốc = điểm mẫu
            ax = (alon[s] - slon) * kx
            ay = (alat[s] - slat) * M_PER_DEG
            dx = (blon[s] - slon) * kx - ax
            dy = (blat[s] - slat) * M_PER_DEG - ay
            L2 = dx * dx + dy * dy
            t = -(ax * dx + ay * dy) / L2 if L2 > 0 else 0.0
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            px = ax + t * dx
            py = ay + t * dy
            d2 = px * px + py * py
            if d2 >= best_d:
                continue
            if _axis_diff(axis, _axis(dx, dy)) > MAX_HEADING_DIFF:
                continue
            best_d = d2
            best_r = rids[s]
        if best_r is not None:
            votes[best_r] = votes.get(best_r, 0) + 1
    if not votes:
        return None, 0, len(samples)
    rid = max(votes, key=votes.get)
    v = votes[rid]
    if v < MIN_VOTE_RATIO * len(samples):
        return None, v, len(samples)
    return rid, v, len(samples)


# ---------------------------------------------------------------- speed.pack
# Bản nhị phân (mmap) cho app: thay SQL + parse JSON mỗi lần tra tốc độ.
# Little-endian. HEADER 64B:
#   0 b'SPK1' | 4 version u8=1 | 5 res u8 | 6 res u16
#   8 cell_deg_e5 u32 (=1000, 0.01°) | 12 seg_count u32 | 16 cell_count u32
#  20 seg_off_off u32  -> u32[seg_count]   (offset bản ghi đoạn)
#  24 cell_keys_off    -> i32[cell_count]  (latCell*100000+lonCell, tăng dần)
#  28 cell_start_off   -> u32[cell_count+1] (CSR vào cell_segs)
#  32 cell_segs_off    -> u32[cell_segs_count] (chỉ số đoạn)
#  36 cell_segs_count u32 | 40..63 reserved
# Bản ghi đoạn (28B + 8B*n):
#   id u32 | fwd u8 (255=null) | rev u8 | hw_class u8 | src u8 (0=OSM 1=luật 2=biển — infer_speed.py)
#   road_name_id i32 (-1) | osm_way_id i64 (-1) | name_hash i32 | n_pts u16 | res u16
#   pts: (lat_e5 i32, lon_e5 i32) * n
SPK_MAGIC = b"SPK1"
SPK_HEADER = 64


def write_speed_pack(path, segs, cell_rows):
    """segs: list (id, fwd, rev, hw_class, rid, osm, nhash, pts[(lat,lon)]) theo id tăng dần.
    cell_rows: list (cell_key, id) đã sort."""
    idx_of = {}
    body = bytearray()
    seg_off = []
    data_off = SPK_HEADER  # bản ghi ngay sau header
    for i, seg in enumerate(segs):
        sid, fwd, rev, hwc, rid, osm, nh, pts = seg[:8]
        src = seg[8] if len(seg) > 8 else 0
        idx_of[sid] = i
        seg_off.append(data_off + len(body))
        n = min(len(pts), 65535)
        body += struct.pack("<IBBBBiqiHH", sid,
                            255 if fwd is None else max(0, min(254, int(fwd))),
                            255 if rev is None else max(0, min(254, int(rev))),
                            hwc & 0xFF, src & 0xFF,
                            -1 if rid is None else int(rid),
                            -1 if osm is None else int(osm),
                            int(nh), n, 0)
        for la, lo in pts[:n]:
            body += struct.pack("<ii", int(round(la * SCALE)), int(round(lo * SCALE)))
    keys = []
    starts = []
    segs_list = []
    last = None
    for key, sid in cell_rows:
        i = idx_of.get(sid)
        if i is None:
            continue
        if key != last:
            keys.append(key)
            starts.append(len(segs_list))
            last = key
        segs_list.append(i)
    starts.append(len(segs_list))
    seg_off_off = SPK_HEADER + len(body)
    tail = bytearray()
    tail += struct.pack("<%dI" % len(seg_off), *seg_off)
    cell_keys_off = seg_off_off + len(tail)
    tail += struct.pack("<%di" % len(keys), *keys)
    cell_start_off = seg_off_off + len(tail)
    tail += struct.pack("<%dI" % len(starts), *starts)
    cell_segs_off = seg_off_off + len(tail)
    tail += struct.pack("<%dI" % len(segs_list), *segs_list)
    header = struct.pack("<4sBBHIIIIIIII", SPK_MAGIC, 1, 0, 0,
                         int(round(APP_CELL_DEG * SCALE)), len(segs), len(keys),
                         seg_off_off, cell_keys_off, cell_start_off, cell_segs_off,
                         len(segs_list))
    header += b"\x00" * (SPK_HEADER - len(header))
    with open(path, "wb") as f:
        f.write(header)
        f.write(body)
        f.write(tail)
    return os.path.getsize(path)


def main():
    ap = argparse.ArgumentParser(description="Enhance speed_limit.db: match đường tên + speed_cells index")
    ap.add_argument("speed_db", help="speed_limit.db gốc")
    ap.add_argument("roads_name_db", help="roads_name.db (đúng bản sẽ chép lên máy)")
    ap.add_argument("out_db", help="speed_limit.db đầu ra")
    ap.add_argument("--no-infer", action="store_true",
                    help="không suy tốc độ (biển spds.db + luật) cho đường chưa có dữ liệu")
    ap.add_argument("--spds", help="spds.db (mặc định cạnh roads_name.db)")
    ap.add_argument("--regions", help="regions.db (mặc định cạnh roads_name.db)")
    args = ap.parse_args()

    for p in (args.speed_db, args.roads_name_db):
        if not os.path.exists(p):
            print("Error: not found:", p)
            sys.exit(1)
    if os.path.abspath(args.speed_db) == os.path.abspath(args.out_db):
        print("Error: out_db phải khác speed_db")
        sys.exit(1)

    t_all = time.time()
    print("==> Index đường có tên:", args.roads_name_db, flush=True)
    segs, names, osm, has_osm = build_named_index(args.roads_name_db)

    print("==> Copy", args.speed_db, "->", args.out_db, flush=True)
    shutil.copy2(args.speed_db, args.out_db)
    con = sqlite3.connect(args.out_db)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    cols = [r[1] for r in con.execute("PRAGMA table_info(roads)")]
    for col, typ in (("road_name_id", "INTEGER"), ("osm_way_id", "INTEGER"),
                     ("highway_class", "INTEGER DEFAULT 9"), ("name_hash", "INTEGER DEFAULT 0"),
                     ("minLat", "INTEGER"), ("minLon", "INTEGER"),
                     ("maxLat", "INTEGER"), ("maxLon", "INTEGER")):
        if col not in cols:
            con.execute("ALTER TABLE roads ADD COLUMN %s %s" % (col, typ))
    # Index bbox kiểu (maxLat, minLat, ...) chỉ dùng được cột đầu → vẫn quét nửa bảng
    con.execute("DROP INDEX IF EXISTS idx_roads_bbox")
    con.execute("DROP TABLE IF EXISTS speed_cells")
    con.execute("CREATE TABLE speed_cells (cell INTEGER NOT NULL, road_id INTEGER NOT NULL)")

    rows = con.execute(
        "SELECT id, min_lat, min_long, max_lat, max_long, fwd_max_speed, rev_max_speed, coords FROM roads"
    ).fetchall()
    total = len(rows)
    print("==> Match %d đoạn tốc độ" % total, flush=True)

    updates = []
    cell_rows = []
    pack_segs = []
    matched = 0
    covered = set()
    t0 = time.time()
    for k, (sid, mnla, mnlo, mxla, mxlo, fwd, rev, coords) in enumerate(rows, 1):
        try:
            arr = json.loads(coords)
        except Exception:
            arr = []
        pts = [(p[1], p[0]) for p in arr if len(p) >= 2]  # speed_limit: [lon, lat] tuyệt đối
        rid = match_segment(pts, segs)[0] if len(pts) >= 2 else None
        if rid is not None:
            matched += 1
            covered.add(rid)
        name = names.get(rid) if rid is not None else None
        hwc = highway_class_from_speed(fwd, rev)
        osm_id = osm.get(rid) if rid is not None else None
        nh = name_hash(name)
        if len(pts) >= 2:
            pack_segs.append((sid, fwd, rev, hwc, rid, osm_id, nh, pts))
        updates.append((rid, osm_id, hwc, nh,
                        int(round(mnla * SCALE)), int(round(mnlo * SCALE)),
                        int(round(mxla * SCALE)), int(round(mxlo * SCALE)), sid))
        for y in range(app_cell(mnla), app_cell(mxla) + 1):
            for x in range(app_cell(mnlo), app_cell(mxlo) + 1):
                cell_rows.append((y * APP_KEY_MUL + x, sid))
        if k % 20000 == 0 or k == total:
            el = max(time.time() - t0, 1e-6)
            print("    %d/%d matched=%d (%.1f%%) %.0f/s ETA %.0fs" % (
                k, total, matched, matched * 100.0 / k, k / el, (total - k) / (k / el)), flush=True)

    con.executemany(
        "UPDATE roads SET road_name_id=?, osm_way_id=?, highway_class=?, name_hash=?,"
        " minLat=?, minLon=?, maxLat=?, maxLon=? WHERE id=?", updates)
    cell_rows.sort()
    con.executemany("INSERT INTO speed_cells(cell, road_id) VALUES (?, ?)", cell_rows)
    print("==> Index...", flush=True)
    # (cell, road_id): covering index — query chỉ đọc index, không chạm bảng speed_cells
    con.execute("CREATE INDEX idx_speed_cells ON speed_cells(cell, road_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_speed_road_name ON roads(road_name_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_speed_osm_way ON roads(osm_way_id)")
    con.execute("ANALYZE")
    con.commit()
    con.execute("VACUUM")
    con.close()

    pack_path = os.path.join(os.path.dirname(os.path.abspath(args.out_db)), "speed.pack")
    pack_cells = list(cell_rows)
    if not args.no_infer:
        import infer_speed
        base = os.path.dirname(os.path.abspath(args.roads_name_db))
        spds = args.spds or os.path.join(base, "spds.db")
        regs = args.regions or os.path.join(base, "regions.db")
        print("==> Suy tốc độ cho đường chưa có dữ liệu", flush=True)
        extra = infer_speed.build(args.roads_name_db,
                                  regs if os.path.exists(regs) else None,
                                  spds if os.path.exists(spds) else None,
                                  segs, covered,
                                  max([r[0] for r in rows] or [0]) + 1)
        for e in extra:
            pts = e[7]
            la = [p[0] for p in pts]
            lo = [p[1] for p in pts]
            for y in range(app_cell(min(la)), app_cell(max(la)) + 1):
                for x in range(app_cell(min(lo)), app_cell(max(lo)) + 1):
                    pack_cells.append((y * APP_KEY_MUL + x, e[0]))
        pack_segs.extend(extra)
        pack_cells.sort()
    pack_segs.sort(key=lambda r: r[0])
    sz = write_speed_pack(pack_path, pack_segs, pack_cells)
    print("==> speed.pack %d đoạn, %.1f MB -> %s" % (len(pack_segs), sz / 1048576.0, pack_path))

    print("==> Xong %.0fs: matched %d/%d (%.1f%%), speed_cells=%d, osm_way_id=%s" % (
        time.time() - t_all, matched, total, matched * 100.0 / total, len(cell_rows),
        "có" if has_osm else "không (roads_name.db thiếu cột)"))
    print("    Output:", args.out_db)


if __name__ == "__main__":
    main()
