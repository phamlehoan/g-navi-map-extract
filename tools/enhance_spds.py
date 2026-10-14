#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Enhance spds.db with grid index for fast camera/sign queries.

spds table: id, x (lon), y (lat), s (speed), t (type), d (direction)

Adds:
  - sign_cells(cell, sign_id) grid index (100m cells)
  - Composite index on (y, x) for bbox fallback
  - Normalized integer coordinates (lat_i, lon_i * 1e7)

Usage:
  python enhance_spds.py data_source/spds.db data_source/enhanced_spds.db
"""
from __future__ import print_function

import argparse
import os
import sqlite3
import sys
import time

SCALE_E7 = 10_000_000
SIGN_GRID_CELL = 100  # 100m grid cells


def grid_key(lat, lon, cell=SIGN_GRID_CELL):
    """Grid key for lat/lon in degrees, cell in meters."""
    lat_cell = int(round(lat * 1e5 / cell))
    lon_cell = int(round(lon * 1e5 / cell))
    return (lat_cell << 32) ^ (lon_cell & 0xFFFFFFFF)


def main():
    ap = argparse.ArgumentParser(description="Enhance spds.db with grid index")
    ap.add_argument("spds_db", help="Input spds.db")
    ap.add_argument("out_db", help="Output enhanced spds.db (e.g., out/alert_data/spds.db)")
    args = ap.parse_args()
    
    if not os.path.exists(args.spds_db):
        print("Error: spds.db not found:", args.spds_db)
        sys.exit(1)
    
    # Copy input to output
    import shutil
    shutil.copy2(args.spds_db, args.out_db)
    
    con = sqlite3.connect(args.out_db)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA temp_store=MEMORY")
    cur = con.cursor()
    
    # Check existing schema
    cols = [r[1] for r in cur.execute("PRAGMA table_info(spds)").fetchall()]
    print("==> Existing columns:", cols)
    
    # Add normalized integer coordinate columns
    new_cols = [
        ("lat_i", "INTEGER"),
        ("lon_i", "INTEGER"),
    ]
    for col_name, col_type in new_cols:
        if col_name not in cols:
            print("    Adding column:", col_name)
            cur.execute(f"ALTER TABLE spds ADD COLUMN {col_name} {col_type}")
    
    # Populate lat_i, lon_i
    print("==> Populating integer coordinates...")
    # fetchall: executemany trên CÙNG cursor sẽ huỷ SELECT đang lặp
    # (bản cũ chỉ xử lý 5000/76k dòng đầu)
    rows = cur.execute("SELECT id, x, y FROM spds").fetchall()
    batch = []
    for row in rows:
        sid, x, y = row
        if x is not None and y is not None:
            lat_i = int(round(y * SCALE_E7))
            lon_i = int(round(x * SCALE_E7))
            batch.append((lat_i, lon_i, sid))
        if len(batch) >= 5000:
            cur.executemany("UPDATE spds SET lat_i=?, lon_i=? WHERE id=?", batch)
            con.commit()
            batch = []
    if batch:
        cur.executemany("UPDATE spds SET lat_i=?, lon_i=? WHERE id=?", batch)
        con.commit()
    
    # Create sign_cells grid index table
    print("==> Building sign_cells grid index...")
    cur.execute("DROP TABLE IF EXISTS sign_cells")
    cur.execute("""
        CREATE TABLE sign_cells (
            cell INTEGER NOT NULL,
            sign_id INTEGER NOT NULL
        )
    """)
    
    rows = cur.execute(
        "SELECT id, lat_i, lon_i FROM spds WHERE lat_i IS NOT NULL AND lon_i IS NOT NULL").fetchall()
    cell_batch = []
    total = 0
    for row in rows:
        sid, lat_i, lon_i = row
        lat = lat_i / SCALE_E7
        lon = lon_i / SCALE_E7
        cell = grid_key(lat, lon)
        cell_batch.append((cell, sid))
        total += 1
        if len(cell_batch) >= 50000:
            cur.executemany("INSERT INTO sign_cells(cell, sign_id) VALUES (?,?)", cell_batch)
            cell_batch = []
            if total % 100000 == 0:
                print(f"    Indexed {total} signs...")
    if cell_batch:
        cur.executemany("INSERT INTO sign_cells(cell, sign_id) VALUES (?,?)", cell_batch)
    
    print(f"    Total signs indexed: {total}")
    
    # Create indexes
    print("==> Creating indexes...")
    cur.execute("CREATE INDEX idx_sign_cells_cell ON sign_cells(cell)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_spds_yx ON spds(y, x)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_spds_lat_i ON spds(lat_i)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_spds_lon_i ON spds(lon_i)")
    cur.execute("ANALYZE")
    con.commit()
    
    # Stats
    cur.execute("SELECT COUNT(*) FROM spds")
    total_signs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM sign_cells")
    total_cells = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT cell) FROM sign_cells")
    unique_cells = cur.fetchone()[0]
    
    con.close()
    
    print("==> Done")
    print(f"    Total signs: {total_signs}")
    print(f"    Grid entries: {total_cells}")
    print(f"    Unique cells: {unique_cells}")
    print("    Output:", args.out_db)


if __name__ == "__main__":
    main()