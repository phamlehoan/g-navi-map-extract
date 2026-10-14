#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OSM PBF -> traffic_lights.db

Extracts traffic signals from OSM:
  - highway=traffic_signals (node)
  - highway=crossing + crossing=traffic_signals (node)
  - railway=level_crossing (node)

Usage:
  python tools/traffic_lights.py data_source/vietnam.osm.pbf out/alert_data/traffic_lights.db --also data_source/hoangsa_truongsa.pbf
  python tools/traffic_lights.py data_source/vietnam.osm.pbf out_dn/traffic_lights.db --bbox 108.15,16.05,108.25,16.15
"""
from __future__ import print_function

import argparse
import os
import sqlite3
import sys
import time

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

from lib.common import add_common_args, ensure_osmium, resolve_bbox_and_pbfs

ensure_osmium()
import osmium


SCALE_E7 = 10_000_000
LIGHT_GRID_CELL = 100  # 100m grid


def grid_key(lat, lon, cell=LIGHT_GRID_CELL):
    lat_cell = int(round(lat * 1e5 / cell))
    lon_cell = int(round(lon * 1e5 / cell))
    return (lat_cell << 32) ^ (lon_cell & 0xFFFFFFFF)


class TrafficLightHandler(osmium.SimpleHandler):
    def __init__(self, bbox=None):
        super(TrafficLightHandler, self).__init__()
        self.bbox = bbox
        self.lights = []  # (id, lat, lon, direction)
        self.osm_id = 0
        self._t0 = time.time()
        self._last = self._t0

    def _in_bbox(self, lat, lon):
        if self.bbox is None:
            return True
        min_lon, min_lat, max_lon, max_lat = self.bbox
        return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon

    def _progress(self):
        now = time.time()
        if now - self._last < 20:
            return
        self._last = now
        print("... traffic_lights=%d (%.0fs)" % (len(self.lights), now - self._t0), flush=True)

    def node(self, n):
        if not n.location.valid():
            return
        lat = n.location.lat
        lon = n.location.lon
        if not self._in_bbox(lat, lon):
            return

        tags = {t.k: t.v for t in n.tags}
        
        is_signal = False
        direction = 0  # 0=unknown, 1=forward, -1=backward, 2=both
        
        # highway=traffic_signals
        if tags.get("highway") == "traffic_signals":
            is_signal = True
            # direction from traffic_signals:direction if present
            td = tags.get("traffic_signals:direction")
            if td == "forward":
                direction = 1
            elif td == "backward":
                direction = -1
            else:
                direction = 2
        
        # highway=crossing + crossing=traffic_signals
        elif tags.get("highway") == "crossing" and tags.get("crossing") == "traffic_signals":
            is_signal = True
            direction = 2
        
        # railway=level_crossing
        elif tags.get("railway") == "level_crossing":
            is_signal = True
            direction = 2
        
        if not is_signal:
            return
        
        self.osm_id += 1
        self.lights.append((self.osm_id, lat, lon, direction))
        self._progress()


def main():
    ap = argparse.ArgumentParser(description="OSM PBF -> traffic_lights.db")
    ap.add_argument("pbf", help="Input .osm.pbf")
    ap.add_argument("out_db", help="Output traffic_lights.db")
    add_common_args(ap)
    args = ap.parse_args()

    bbox, pbfs, provinces = resolve_bbox_and_pbfs(args)

    out_dir = os.path.dirname(os.path.abspath(args.out_db))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()
    h = TrafficLightHandler(bbox=bbox)
    for pbf in pbfs:
        print("==> Scanning", pbf, flush=True)
        h.apply_file(pbf, locations=True)
    
    print("==> Found %d traffic lights in %.0fs" % (len(h.lights), time.time() - t0), flush=True)

    if os.path.exists(args.out_db):
        os.remove(args.out_db)
    con = sqlite3.connect(args.out_db)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA temp_store=MEMORY")
    cur = con.cursor()

    # Schema compatible with app (x=lon, y=lat, d=direction)
    cur.execute("""
        CREATE TABLE traffic_lights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            x REAL NOT NULL,
            y REAL NOT NULL,
            d INTEGER DEFAULT 0
        )
    """)

    # Integer coordinates for grid index
    cur.execute("ALTER TABLE traffic_lights ADD COLUMN lat_i INTEGER")
    cur.execute("ALTER TABLE traffic_lights ADD COLUMN lon_i INTEGER")

    # Insert lights
    batch = []
    for lid, lat, lon, direction in h.lights:
        lat_i = int(round(lat * SCALE_E7))
        lon_i = int(round(lon * SCALE_E7))
        batch.append((lon, lat, direction, lat_i, lon_i))
        if len(batch) >= 5000:
            cur.executemany(
                "INSERT INTO traffic_lights(x, y, d, lat_i, lon_i) VALUES (?,?,?,?,?)",
                batch
            )
            batch = []
    if batch:
        cur.executemany(
            "INSERT INTO traffic_lights(x, y, d, lat_i, lon_i) VALUES (?,?,?,?,?)",
            batch
        )

    # Grid index
    print("==> Building light_cells grid index...")
    cur.execute("""
        CREATE TABLE light_cells (
            cell INTEGER NOT NULL,
            light_id INTEGER NOT NULL
        )
    """)
    cell_batch = []
    for lid, lat, lon, direction in h.lights:
        cell = grid_key(lat, lon)
        cell_batch.append((cell, lid))
        if len(cell_batch) >= 50000:
            cur.executemany("INSERT INTO light_cells(cell, light_id) VALUES (?,?)", cell_batch)
            cell_batch = []
    if cell_batch:
        cur.executemany("INSERT INTO light_cells(cell, light_id) VALUES (?,?)", cell_batch)

    # Indexes
    print("==> Creating indexes...")
    cur.execute("CREATE INDEX idx_light_cells_cell ON light_cells(cell)")
    cur.execute("CREATE INDEX idx_lights_yx ON traffic_lights(y, x)")
    cur.execute("CREATE INDEX idx_lights_lat_i ON traffic_lights(lat_i)")
    cur.execute("CREATE INDEX idx_lights_lon_i ON traffic_lights(lon_i)")
    cur.execute("ANALYZE")
    con.commit()
    con.close()

    sz = os.path.getsize(args.out_db) / (1024 * 1024.0)
    print("==> Done %.1fs -> %s (%.1f MB)" % (time.time() - t0, args.out_db, sz), flush=True)


if __name__ == "__main__":
    main()