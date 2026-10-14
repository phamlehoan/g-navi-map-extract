#!/usr/bin/env python3
"""Xuất names.pack (NMP1) từ roads_name.db — app đọc bằng mmap thay SQL road_cells.

Chỉ đường CÓ tên. Toạ độ giữ nguyên chuỗi JSON `coordinates` (app đã cache polyline
đã parse theo chuỗi) — pack chỉ bỏ chi phí SQLite/Cursor khi đổi vùng.

Layout (little-endian):
  header 64B: "NMP1", ver=1, cellUnits(1e-5°), roadCount, cellCount,
              recOffOff, cellKeysOff, cellStartOff, cellRoadsOff
  recOff[roadCount] int32
  cellKeys[cellCount] int64 (cy*1_000_000+cx, tăng dần)
  cellStart[cellCount+1] int32
  cellRoads[] int32 (chỉ số road)
  records: minLat,maxLat,minLon,maxLon int32 | nameLen u16 | name utf8 | coordLen int32 | coords utf8
Dùng: python names_pack.py roads_name.db [names.pack]
"""
import os
import sqlite3
import struct
import sys

CELL = 1000  # = ROAD_GRID_CELL trong app (0.01°)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(src)), "names.pack")
    con = sqlite3.connect(src)
    rows = con.execute(
        "SELECT name, minLat, maxLat, minLon, maxLon, coordinates FROM roads "
        "WHERE name IS NOT NULL AND length(name)>0 ORDER BY minLat, minLon").fetchall()
    con.close()
    recs = bytearray()
    rec_off = []
    cells = {}
    for i, (name, a, b, c, d, coords) in enumerate(rows):
        rec_off.append(len(recs))
        nb = name.encode("utf-8")[:65535]
        cb = (coords or "").encode("utf-8")
        recs += struct.pack("<iiiiH", a, b, c, d, len(nb)) + nb + struct.pack("<i", len(cb)) + cb
        for cy in range(a // CELL, b // CELL + 1):
            for cx in range(c // CELL, d // CELL + 1):
                cells.setdefault(cy * 1000000 + cx, []).append(i)
    keys = sorted(cells)
    n, m = len(rows), len(keys)
    rec_off_off = 64
    keys_off = rec_off_off + 4 * n
    start_off = keys_off + 8 * m
    roads_off = start_off + 4 * (m + 1)
    total_cr = sum(len(cells[k]) for k in keys)
    data_off = roads_off + 4 * total_cr
    with open(out + ".tmp", "wb") as f:
        f.write(struct.pack("<4siiiiiiii", b"NMP1", 1, CELL, n, m,
                            rec_off_off, keys_off, start_off, roads_off).ljust(64, b"\0"))
        f.write(struct.pack("<%di" % n, *[o + data_off for o in rec_off]))
        f.write(struct.pack("<%dq" % m, *keys))
        acc, starts = 0, []
        for k in keys:
            starts.append(acc)
            acc += len(cells[k])
        starts.append(acc)
        f.write(struct.pack("<%di" % (m + 1), *starts))
        for k in keys:
            f.write(struct.pack("<%di" % len(cells[k]), *cells[k]))
        f.write(recs)
    os.replace(out + ".tmp", out)
    print("==> names.pack %d đường, %d ô, %.1f MB -> %s" % (
        n, m, os.path.getsize(out) / 1048576.0, out))


if __name__ == "__main__":
    main()
