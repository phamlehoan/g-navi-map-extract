#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Xuất regions.db (phường / tỉnh) từ OSM PBF — schema GNavi / Car Launcher.

  wards(id, ward, province, min_lat, max_lat, min_lon, max_lon, cordinates)
  cordinates = JSON [[lon,lat],...] (outer ring; typo 'cordinates' giữ đúng app)

Usage:
  python regions.py vietnam.osm.pbf out/alert_data/regions.db
  python regions.py vietnam.osm.pbf out/alert_data/regions.db --provinces "Ha Tinh,Da Nang,Quang Nam"
  python regions.py vietnam.osm.pbf out.db --bbox 108.0,15.9,108.4,16.3

Cần RAM nhiều (ghép multipolygon). Docker: -m 4g trở lên.
"""
from __future__ import print_function

import argparse
import json
import os
import sqlite3
import sys
import time

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from lib.common import add_common_args, ensure_osmium, resolve_bbox_and_pbfs
from lib.osm_names import place_name
from lib.vn_provinces import map_old_province_to_new

ensure_osmium()
import osmium  # noqa: E402


def point_in_ring(lon, lat, ring):
    """Ray casting; ring = [(lon,lat), ...]"""
    n = len(ring)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi
        ):
            inside = not inside
        j = i
    return inside


def simplify_ring(ring, max_pts=800):
    if len(ring) <= max_pts:
        return ring
    step = max(1, len(ring) // max_pts)
    out = ring[::step]
    if out[-1] != ring[-1]:
        out.append(ring[-1])
    return out


class BoundaryHandler(osmium.SimpleHandler):
    def __init__(self, bbox=None):
        super(BoundaryHandler, self).__init__()
        self.bbox = bbox
        self.provinces = []  # (name, rings, bbox)
        self.wards = []
        self._t0 = time.time()
        self._last = self._t0
        self.areas_seen = 0

    def _in_bbox_poly(self, min_lon, min_lat, max_lon, max_lat):
        if self.bbox is None:
            return True
        bmin_lon, bmin_lat, bmax_lon, bmax_lat = self.bbox
        return not (max_lon < bmin_lon or min_lon > bmax_lon
                    or max_lat < bmin_lat or min_lat > bmax_lat)

    def area(self, a):
        tags = {t.k: t.v for t in a.tags}
        if tags.get("boundary") not in ("administrative", "census"):
            return
        level = tags.get("admin_level")
        if level not in ("4", "6", "8"):
            return
        name = place_name(tags)
        if not name:
            return
        self.areas_seen += 1

        rings = []
        min_lat = 90.0
        max_lat = -90.0
        min_lon = 180.0
        max_lon = -180.0
        try:
            for outer in a.outer_rings():
                ring = []
                for n in outer:
                    if not n.location.valid():
                        continue
                    la = n.lat
                    lo = n.lon
                    ring.append((lo, la))
                    if la < min_lat:
                        min_lat = la
                    if la > max_lat:
                        max_lat = la
                    if lo < min_lon:
                        min_lon = lo
                    if lo > max_lon:
                        max_lon = lo
                if len(ring) >= 3:
                    rings.append(simplify_ring(ring))
        except Exception:
            return
        if not rings:
            return
        if not self._in_bbox_poly(min_lon, min_lat, max_lon, max_lat):
            return

        # tag tỉnh nếu có
        province_tag = (
            tags.get("is_in:province")
            or tags.get("is_in:state")
            or tags.get("addr:province")
            or tags.get("addr:state")
        )
        item = {
            "name": name,
            "rings": rings,
            "min_lat": min_lat,
            "max_lat": max_lat,
            "min_lon": min_lon,
            "max_lon": max_lon,
            "province_tag": province_tag.strip() if province_tag else None,
        }
        if level == "4":
            self.provinces.append(item)
        else:
            self.wards.append(item)

        now = time.time()
        if now - self._last >= 15:
            self._last = now
            print("... areas=%d provinces=%d wards=%d (%.0fs)" % (
                self.areas_seen, len(self.provinces), len(self.wards),
                now - self._t0), flush=True)


def find_province(ward, provinces):
    if ward.get("province_tag"):
        return map_old_province_to_new(ward["province_tag"])
    # centroid rough
    ring0 = ward["rings"][0]
    lon = sum(p[0] for p in ring0) / float(len(ring0))
    lat = sum(p[1] for p in ring0) / float(len(ring0))
    for p in provinces:
        if not (p["min_lat"] <= lat <= p["max_lat"]
                and p["min_lon"] <= lon <= p["max_lon"]):
            continue
        for ring in p["rings"]:
            if point_in_ring(lon, lat, ring):
                return map_old_province_to_new(p["name"])
    return None


def open_db(path):
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute(
        """CREATE TABLE wards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ward TEXT,
            province TEXT,
            min_lat REAL,
            max_lat REAL,
            min_lon REAL,
            max_lon REAL,
            cordinates TEXT
        )"""
    )
    return con


def main():
    ap = argparse.ArgumentParser(description="OSM PBF → regions.db")
    ap.add_argument("pbf")
    ap.add_argument("out_db")
    add_common_args(ap)
    args = ap.parse_args()
    bbox, pbfs, provinces = resolve_bbox_and_pbfs(args)

    # Build set of requested province IDs for filtering
    requested_province_ids = set(p["id"] for p in provinces) if provinces else None

    out_dir = os.path.dirname(os.path.abspath(args.out_db))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()
    h = BoundaryHandler(bbox=bbox)
    for pbf in pbfs:
        print("==> regions from", pbf, "(assembling areas...)", flush=True)
        h.apply_file(pbf, locations=True)
    print("==> collected provinces=%d wards=%d" % (
        len(h.provinces), len(h.wards)), flush=True)

    con = open_db(args.out_db)
    sql = (
        "INSERT INTO wards(ward,province,min_lat,max_lat,min_lon,max_lon,cordinates) "
        "VALUES (?,?,?,?,?,?,?)"
    )
    batch = []
    n = 0
    skipped = 0
    for w in h.wards:
        prov = find_province(w, h.provinces)
        if not prov:
            skipped += 1
            continue
        # Filter to only requested provinces
        if requested_province_ids:
            # Map province name back to ID for comparison
            from lib.vn_provinces import _norm, all_provinces
            prov_id = None
            for p in all_provinces():
                if _norm(p["name"]) == _norm(prov):
                    prov_id = p["id"]
                    break
            if prov_id and prov_id not in requested_province_ids:
                skipped += 1
                continue
        # outer ring đầu (đủ cho PIP app)
        ring = w["rings"][0]
        coords = [[round(lo, 5), round(la, 5)] for lo, la in ring]
        batch.append((
            w["name"], prov,
            w["min_lat"], w["max_lat"], w["min_lon"], w["max_lon"],
            json.dumps(coords, separators=(",", ":"), ensure_ascii=False),
        ))
        n += 1
        if len(batch) >= 200:
            con.executemany(sql, batch)
            con.commit()
            batch = []
    if batch:
        con.executemany(sql, batch)
        con.commit()

    con.execute("CREATE INDEX idx_bbox_lat ON wards(min_lat, max_lat)")
    con.execute("CREATE INDEX idx_bbox_lon ON wards(min_lon, max_lon)")
    # Composite index for bbox queries (matches SpeedAlertRepository.createBboxIndexesAsync)
    con.execute("CREATE INDEX idx_wards_bbox ON wards(max_lat, min_lat, max_lon, min_lon)")
    con.execute("ANALYZE")
    con.commit()
    con.close()
    sz = os.path.getsize(args.out_db) / (1024 * 1024.0)
    print("==> Done wards=%d skipped_no_province=%d size=%.1f MB in %.1fs -> %s" % (
        n, skipped, sz, time.time() - t0, args.out_db), flush=True)


if __name__ == "__main__":
    main()
