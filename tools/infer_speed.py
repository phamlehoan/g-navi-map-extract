# -*- coding: utf-8 -*-
"""Tốc độ SUY RA cho đường có tên chưa có đoạn speed_limit (dùng trong enhance_speed_limit.py).

Thứ tự ưu tiên cho mỗi đường (mỗi chiều):
  1. Biển báo tốc độ trong spds.db (t=1, s=km/h) nằm sát đường (≤ SIGN_RADIUS_M), cùng phương,
     chiều theo hướng d của biển  -> SRC_SIGN.
  2. Mức mặc định Thông tư 38/2024/TT-BGTVT (đường 2 chiều / 1 làn — không biết số làn nên lấy
     mức thấp hơn):  trong khu đông dân cư 50, ngoài khu đông dân cư 80        -> SRC_LAW.
     Khu đông dân cư: đường trong Phường/Thị trấn; trong Xã/Đặc khu chỉ QL/ĐT/TL tính là ngoài
     khu dân cư, đường tên khác (đường làng, phố xã) tính là trong khu dân cư.
  Bỏ qua đường tên "Cao tốc" (biển riêng, không suy).
Kết quả chỉ ghi vào speed.pack (byte nguồn), không ghi vào speed_limit.db.
"""
from __future__ import print_function

import json
import math
import re
import sqlite3
import time

SRC_OSM = 0
SRC_LAW = 1
SRC_SIGN = 2

LAW_URBAN = 50
LAW_RURAL = 80
SIGN_RADIUS_M = 25.0
SIGN_AXIS_DIFF = 30.0
M_PER_DEG = 111320.0
SCALE = 100000
WARD_CELL = 0.05

_MAJOR = re.compile(r"^\s*(ql|quốc lộ|quoc lo|đt|dt|đường tỉnh|duong tinh|tỉnh lộ|tinh lo|tl)[\s\.\-]*\d",
                    re.IGNORECASE)
_EXPRESS = re.compile(r"cao tốc|cao toc|expressway", re.IGNORECASE)


def _bearing(la1, lo1, la2, lo2):
    dy = (la2 - la1)
    dx = (lo2 - lo1) * math.cos(math.radians(la1))
    return math.degrees(math.atan2(dx, dy)) % 360.0


def _adiff(a, b):
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _rings(obj):
    """cordinates: [[lon,lat],...] hoặc lồng nhiều vòng."""
    if not obj:
        return []
    if isinstance(obj[0][0], (int, float)):
        return [obj]
    out = []
    for o in obj:
        out.extend(_rings(o))
    return out


class Wards(object):
    def __init__(self, path):
        self.items = []
        self.grid = {}
        try:
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
            rows = con.execute("SELECT ward, min_lat, max_lat, min_lon, max_lon, cordinates FROM wards").fetchall()
            con.close()
        except Exception as e:
            print("    regions.db không đọc được (%s) -> coi mọi đường là trong khu dân cư" % e)
            rows = []
        for ward, a, b, c, d, coords in rows:
            try:
                rings = _rings(json.loads(coords))
            except Exception:
                continue
            w = (ward or "").strip().lower()
            urban = w.startswith(u"phường") or w.startswith(u"thị trấn") or w.startswith(u"thị xã")
            i = len(self.items)
            self.items.append((a, b, c, d, rings, urban))
            for y in range(int(math.floor(a / WARD_CELL)), int(math.floor(b / WARD_CELL)) + 1):
                for x in range(int(math.floor(c / WARD_CELL)), int(math.floor(d / WARD_CELL)) + 1):
                    self.grid.setdefault((y, x), []).append(i)

    def urban(self, lat, lon):
        """True/False; None nếu không thuộc ward nào."""
        for i in self.grid.get((int(math.floor(lat / WARD_CELL)), int(math.floor(lon / WARD_CELL))), ()):
            a, b, c, d, rings, urban = self.items[i]
            if lat < a or lat > b or lon < c or lon > d:
                continue
            inside = False
            for r in rings:
                j = len(r) - 1
                for k in range(len(r)):
                    xi, yi = r[k][0], r[k][1]
                    xj, yj = r[j][0], r[j][1]
                    if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
                        inside = not inside
                    j = k
            if inside:
                return urban
        return None


def _load_signs(spds_path):
    try:
        con = sqlite3.connect("file:%s?mode=ro" % spds_path, uri=True)
        rows = con.execute("SELECT y, x, s, d FROM spds WHERE t=1 AND s>0").fetchall()
        con.close()
        return rows
    except Exception as e:
        print("    spds.db không đọc được (%s) -> chỉ dùng mức luật" % e)
        return []


def _assign_signs(signs, segs):
    """Mỗi biển → (road_id, chiều fwd/rev, km/h) qua lưới đoạn đường-tên của match."""
    alat, alon, blat, blon, rids, seg_order, cells = segs
    from enhance_speed_limit import seg_key
    out = {}  # rid -> {'f': [..], 'r': [..]}
    r2 = SIGN_RADIUS_M * SIGN_RADIUS_M
    for slat, slon, s, d in signs:
        rng = cells.get(seg_key(slat, slon))
        if rng is None:
            continue
        kx = M_PER_DEG * math.cos(math.radians(slat))
        best = None
        best_d = r2
        for j in range(rng[0], rng[1]):
            g = seg_order[j]
            ax = (alon[g] - slon) * kx
            ay = (alat[g] - slat) * M_PER_DEG
            dx = (blon[g] - slon) * kx - ax
            dy = (blat[g] - slat) * M_PER_DEG - ay
            L2 = dx * dx + dy * dy
            t = -(ax * dx + ay * dy) / L2 if L2 > 0 else 0.0
            t = 0.0 if t < 0 else (1.0 if t > 1 else t)
            px, py = ax + t * dx, ay + t * dy
            dd = px * px + py * py
            if dd >= best_d:
                continue
            brg = math.degrees(math.atan2(dx, dy)) % 360.0
            diff = _adiff(brg, d or 0)
            if d is None or (SIGN_AXIS_DIFF < diff < 180 - SIGN_AXIS_DIFF):
                continue
            best_d = dd
            best = (rids[g], 'f' if diff <= 90 else 'r')
        if best is not None:
            out.setdefault(best[0], {'f': [], 'r': []})[best[1]].append(int(s))
    return out


def _mode(vals):
    if not vals:
        return None
    c = {}
    for v in vals:
        c[v] = c.get(v, 0) + 1
    return max(sorted(c), key=c.get)


def _merge(pending, start_id):
    """Gộp các đường cùng tên + cùng (fwd, rev, nguồn) mà đầu-cuối nối liền nhau → ít bản ghi hơn.

    Mỗi bản ghi pack tốn 28B header + 1 lần load/duyệt khi tra; đường dài bị OSM cắt thành rất
    nhiều way ngắn. Chỉ nối khi đầu của đoạn sau trùng cuối đoạn trước (<= ~1m) — hình học
    không đổi nên khớp đường vẫn như cũ. Giữ osm_way_id/road_name_id của đoạn đầu.
    """
    groups = {}
    for it in pending:
        rid, name, fwd, rev, src, osm, pts = it
        groups.setdefault((name, fwd, rev, src), []).append(it)
    tol = 1.0 / M_PER_DEG
    merged = []
    for key, items in groups.items():
        by_start = {}
        for i, it in enumerate(items):
            by_start.setdefault((round(it[6][0][0] / tol), round(it[6][0][1] / tol)), []).append(i)
        used = [False] * len(items)
        for i, it in enumerate(items):
            if used[i]:
                continue
            used[i] = True
            rid, name, fwd, rev, src, osm, pts = it
            pts = list(pts)
            while len(pts) < 60000:
                k = (round(pts[-1][0] / tol), round(pts[-1][1] / tol))
                nxt = next((j for j in by_start.get(k, ()) if not used[j]), None)
                if nxt is None:
                    break
                used[nxt] = True
                pts.extend(items[nxt][6][1:])
            merged.append((rid, name, fwd, rev, src, osm, pts))
    out = []
    sid = start_id
    for rid, name, fwd, rev, src, osm, pts in merged:
        out.append((sid, fwd, rev, 9, rid, osm, 0, pts, src))
        sid += 1
    return out


def build(roads_name_db, regions_db, spds_db, segs, covered_rids, start_id):
    """→ list (id, fwd, rev, hw_class, rid, osm, nhash, pts, src)."""
    t0 = time.time()
    signs = _load_signs(spds_db) if spds_db else []
    by_road = _assign_signs(signs, segs) if signs else {}
    print("    biển tốc độ: %d, gắn được vào %d đường" % (len(signs), len(by_road)), flush=True)
    wards = Wards(regions_db) if regions_db else None

    con = sqlite3.connect("file:%s?mode=ro" % roads_name_db, uri=True)
    cols = [r[1] for r in con.execute("PRAGMA table_info(roads)")]
    has_osm = 'osm_way_id' in cols
    q = ("SELECT id, name, minLat, minLon, coordinates" + (", osm_way_id" if has_osm else "")
         + " FROM roads WHERE name IS NOT NULL AND length(name) > 1")
    pending = []
    n_sign = n_law = 0
    sid = start_id
    for row in con.execute(q):
        rid, name = row[0], row[1]
        if rid in covered_rids or _EXPRESS.search(name):
            continue
        try:
            arr = json.loads(row[4])
        except Exception:
            continue
        arr = [p for p in arr if len(p) >= 2]
        if len(arr) < 2:
            continue
        deg = any(p[0] != int(p[0]) or p[1] != int(p[1]) for p in arr)
        div = 1.0 if deg else float(SCALE)
        bla, blo = row[2] / float(SCALE), row[3] / float(SCALE)
        pts = [(bla + p[1] / div, blo + p[0] / div) for p in arr]
        sg = by_road.get(rid)
        fwd = _mode(sg['f']) if sg else None
        rev = _mode(sg['r']) if sg else None
        if fwd is not None or rev is not None:
            src = SRC_SIGN
            n_sign += 1
        else:
            src = SRC_LAW
            n_law += 1
        if fwd is None or rev is None:
            mid = pts[len(pts) // 2]
            urban = wards.urban(mid[0], mid[1]) if wards else None
            if urban is None:
                urban = True
            law = LAW_URBAN if (urban or not _MAJOR.search(name)) else LAW_RURAL
            fwd = law if fwd is None else fwd
            rev = law if rev is None else rev
        osm = row[5] if has_osm else None
        pending.append((rid, name, fwd, rev, src, osm, pts))
    con.close()
    out = _merge(pending, sid)
    print("    gộp đoạn cùng tên + cùng tốc độ: %d -> %d" % (len(pending), len(out)), flush=True)
    print("    suy tốc độ: %d đường theo biển, %d theo luật (%.0fs)" % (
        n_sign, n_law, time.time() - t0), flush=True)
    return out
