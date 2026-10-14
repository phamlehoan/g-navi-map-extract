#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Binary road tile format (.rmap) — shared encode helpers.

Layout (little-endian):

  VERSION 1 (legacy, no index):
    HEADER 40 bytes — names @40, roads follow

  VERSION 2 (có cell index):
    HEADER 48 bytes
      0  magic          b'RMAP'
      4  version        u8 (=2)
      5  reserved       u8
      6  chunk_units    u16
      8  tile_cy        i32
     12  tile_cx        i32
     16  origin_lat     i32   (= cy * chunk_units, SCALE 1e5)
     20  origin_lon     i32
     24  road_count     u32
     28  name_count     u32
     32  names_offset   u32
     36  roads_offset   u32
     40  index_offset   u32   # 0 = none; else RIDX section
     44  reserved2      u32

  NAME POOL @ names_offset
  ROADS @ roads_offset (sequential) — same as v1
  RIDX @ index_offset (v2):
    0  magic          b'RIDX'
    4  version        u8 (=1)
    5  reserved       u8
    6  cell_units     u16   # SCALE units / cell (~0.002° = 200)
    8  cells_y        u16
   10  cells_x        u16
   12  grid_origin_lat i32  # absolute SCALE, SW of cell (0,0)
   16  grid_origin_lon i32
   20  road_count     u32
   24  — then —
      u32 road_offs[road_count]          # file offset mỗi road record
      u32 cell_off[cells_y*cells_x + 1]  # CSR vào road_ids
      u16 road_ids[]                     # road index per cell
"""
from __future__ import print_function

import struct
import zlib

MAGIC = b"RMAP"
VERSION = 2
VERSION_LEGACY = 1
HEADER_SIZE = 48
HEADER_SIZE_V1 = 40
NAME_NONE = 0xFFFF
FLAG_MAJOR = 1
SCALE = 100000

# ~0.002° ≈ 220m — đủ mịn cho snap/queryAround, nhẹ trên HU
DEFAULT_CELL_UNITS = 200

RIDX_MAGIC = b"RIDX"
RIDX_VERSION = 1
RIDX_HEADER = 24

MAJOR_PREFIXES = ("QL", "ĐL", "CT", "Hầm", "Cầu")


def is_major_name(name):
    if not name:
        return False
    for p in MAJOR_PREFIXES:
        if name.startswith(p):
            return True
    return False


def decode_coords_blob(blob, min_lat_i, min_lon_i):
    """Return list of (lat_i, lon_i) int SCALE, or None."""
    if not blob or len(blob) < 6:
        return None
    if blob[0:1] != b"R" and blob[0] != ord("R"):
        return None
    if blob[1] != 1:
        return None
    n = struct.unpack_from("<I", blob, 2)[0]
    if n < 2 or len(blob) < 6 + n * 8:
        return None
    pts = []
    off = 6
    for _ in range(n):
        dlon, dlat = struct.unpack_from("<ii", blob, off)
        off += 8
        pts.append((min_lat_i + dlat, min_lon_i + dlon))
    return pts


def clip_polyline(pts, min_lat, max_lat, min_lon, max_lon):
    """Cohen–Sutherland-ish segment clip; returns list of polylines (each ≥2 pts)."""
    if not pts or len(pts) < 2:
        return []

    def lerp(a, b, t):
        return int(round(a + (b - a) * t))

    def clip_segment(lat1, lon1, lat2, lon2):
        for _ in range(8):
            c1 = ((lat1 < min_lat) | ((lat1 > max_lat) << 1)
                  | ((lon1 < min_lon) << 2) | ((lon1 > max_lon) << 3))
            c2 = ((lat2 < min_lat) | ((lat2 > max_lat) << 1)
                  | ((lon2 < min_lon) << 2) | ((lon2 > max_lon) << 3))
            if c1 == 0 and c2 == 0:
                return lat1, lon1, lat2, lon2
            if c1 & c2:
                return None
            code = c1 or c2
            if code & 1:
                t = (min_lat - lat1) / float(lat2 - lat1) if lat2 != lat1 else 0
                lon = lerp(lon1, lon2, t)
                lat = min_lat
            elif code & 2:
                t = (max_lat - lat1) / float(lat2 - lat1) if lat2 != lat1 else 0
                lon = lerp(lon1, lon2, t)
                lat = max_lat
            elif code & 4:
                t = (min_lon - lon1) / float(lon2 - lon1) if lon2 != lon1 else 0
                lat = lerp(lat1, lat2, t)
                lon = min_lon
            else:
                t = (max_lon - lon1) / float(lon2 - lon1) if lon2 != lon1 else 0
                lat = lerp(lat1, lat2, t)
                lon = max_lon
            if code == c1:
                lat1, lon1 = lat, lon
            else:
                lat2, lon2 = lat, lon
        return None

    out = []
    cur = []
    for i in range(len(pts) - 1):
        la1, lo1 = pts[i]
        la2, lo2 = pts[i + 1]
        clipped = clip_segment(la1, lo1, la2, lo2)
        if clipped is None:
            if len(cur) >= 2:
                out.append(cur)
            cur = []
            continue
        cla1, clo1, cla2, clo2 = clipped
        if not cur:
            cur = [(cla1, clo1), (cla2, clo2)]
        else:
            if cur[-1] != (cla1, clo1):
                if len(cur) >= 2:
                    out.append(cur)
                cur = [(cla1, clo1), (cla2, clo2)]
            else:
                cur.append((cla2, clo2))
    if len(cur) >= 2:
        out.append(cur)
    return out


def _build_cell_index(origin_lat, origin_lon, packed_roads, roads_offset, cell_units):
    """Build RIDX bytes; road record offsets computed from packed layout."""
    if cell_units < 50:
        cell_units = DEFAULT_CELL_UNITS

    # Absolute bbox of all points
    min_la = None
    max_la = None
    min_lo = None
    max_lo = None
    for _flags, _nid, xy in packed_roads:
        for x, y in xy:
            la = origin_lat + y
            lo = origin_lon + x
            if min_la is None or la < min_la:
                min_la = la
            if max_la is None or la > max_la:
                max_la = la
            if min_lo is None or lo < min_lo:
                min_lo = lo
            if max_lo is None or lo > max_lo:
                max_lo = lo
    if min_la is None:
        return b""

    # Expand 1 cell
    grid_origin_lat = (min_la // cell_units) * cell_units - cell_units
    grid_origin_lon = (min_lo // cell_units) * cell_units - cell_units
    max_la_pad = max_la + cell_units
    max_lo_pad = max_lo + cell_units
    ny = max(1, (max_la_pad - grid_origin_lat + cell_units - 1) // cell_units)
    nx = max(1, (max_lo_pad - grid_origin_lon + cell_units - 1) // cell_units)
    # Cap lưới quá lớn (tile lệch)
    if ny > 512 or nx > 512:
        cell_units = max(cell_units, max(
            (max_la_pad - grid_origin_lat) // 256 + 1,
            (max_lo_pad - grid_origin_lon) // 256 + 1,
        ))
        grid_origin_lat = (min_la // cell_units) * cell_units - cell_units
        grid_origin_lon = (min_lo // cell_units) * cell_units - cell_units
        ny = max(1, (max_la + cell_units - grid_origin_lat + cell_units - 1) // cell_units)
        nx = max(1, (max_lo + cell_units - grid_origin_lon + cell_units - 1) // cell_units)
        ny = min(ny, 512)
        nx = min(nx, 512)

    n_cells = ny * nx
    buckets = [[] for _ in range(n_cells)]

    def add_cell(rid, la, lo):
        gy = (la - grid_origin_lat) // cell_units
        gx = (lo - grid_origin_lon) // cell_units
        if gy < 0 or gx < 0 or gy >= ny or gx >= nx:
            return
        buckets[gy * nx + gx].append(rid)

    road_offs = []
    o = roads_offset
    for rid, (flags, nid, xy) in enumerate(packed_roads):
        road_offs.append(o)
        n = len(xy)
        if n > 65535:
            n = 65535
        o += 5 + n * 4
        # Index mọi điểm + midpoint đoạn
        seen = set()
        for x, y in xy[:n]:
            la = origin_lat + y
            lo = origin_lon + x
            gy = (la - grid_origin_lat) // cell_units
            gx = (lo - grid_origin_lon) // cell_units
            key = (gy, gx)
            if key in seen:
                continue
            seen.add(key)
            add_cell(rid, la, lo)
        for i in range(n - 1):
            x0, y0 = xy[i]
            x1, y1 = xy[i + 1]
            la = origin_lat + ((y0 + y1) // 2)
            lo = origin_lon + ((x0 + x1) // 2)
            add_cell(rid, la, lo)

    # Dedupe per bucket, preserve order
    for i in range(n_cells):
        if not buckets[i]:
            continue
        uniq = []
        seen_r = set()
        for rid in buckets[i]:
            if rid in seen_r:
                continue
            seen_r.add(rid)
            uniq.append(rid)
        buckets[i] = uniq

    cell_off = [0]
    road_ids = []
    for b in buckets:
        road_ids.extend(b)
        cell_off.append(len(road_ids))

    blob = bytearray()
    blob += struct.pack(
        "<4sBBHHHiiI",
        RIDX_MAGIC,
        RIDX_VERSION,
        0,
        cell_units & 0xFFFF,
        ny & 0xFFFF,
        nx & 0xFFFF,
        grid_origin_lat,
        grid_origin_lon,
        len(packed_roads),
    )
    assert len(blob) == RIDX_HEADER
    for off in road_offs:
        blob += struct.pack("<I", off)
    for off in cell_off:
        blob += struct.pack("<I", off)
    for rid in road_ids:
        blob += struct.pack("<H", rid & 0xFFFF)
    return bytes(blob)


def build_rmap(tile_cy, tile_cx, chunk_units, roads, cell_units=DEFAULT_CELL_UNITS):
    """roads: iterable of (name_or_None, list[(lat_i, lon_i)]).

    Clips each road to tile±pad, packs int16 relative coords, dedupes names,
    embeds RIDX cell grid (version 2).
    Returns bytes or None if empty.
    """
    origin_lat = tile_cy * chunk_units
    origin_lon = tile_cx * chunk_units
    pad = max(chunk_units // 5, 2000)
    min_la = origin_lat - pad
    max_la = origin_lat + chunk_units + pad
    min_lo = origin_lon - pad
    max_lo = origin_lon + chunk_units + pad

    name_to_id = {}
    name_list = []
    packed_roads = []  # (flags, name_id, pts_xy as list of (x,y) i16)

    for name, pts in roads:
        if not pts or len(pts) < 2:
            continue
        for poly in clip_polyline(pts, min_la, max_la, min_lo, max_lo):
            xy = []
            ok = True
            for lat_i, lon_i in poly:
                x = lon_i - origin_lon
                y = lat_i - origin_lat
                if x < -32768 or x > 32767 or y < -32768 or y > 32767:
                    ok = False
                    break
                xy.append((x, y))
            if not ok or len(xy) < 2:
                continue
            if all(xy[i] == xy[0] for i in range(len(xy))):
                continue
            flags = FLAG_MAJOR if is_major_name(name) else 0
            nid = NAME_NONE
            if name and len(name.strip()) >= 2:
                key = name.strip()
                if key not in name_to_id:
                    if len(name_list) >= NAME_NONE:
                        nid = NAME_NONE
                    else:
                        name_to_id[key] = len(name_list)
                        name_list.append(key)
                        nid = name_to_id[key]
                else:
                    nid = name_to_id[key]
            packed_roads.append((flags, nid, xy))

    if not packed_roads:
        return None

    names_blob = bytearray()
    for nm in name_list:
        raw = nm.encode("utf-8")
        if len(raw) > 65535:
            raw = raw[:65535]
        names_blob += struct.pack("<H", len(raw))
        names_blob += raw

    roads_blob = bytearray()
    for flags, nid, xy in packed_roads:
        n = len(xy)
        if n > 65535:
            xy = xy[:65535]
            n = 65535
        roads_blob += struct.pack("<BHH", flags, nid, n)
        for x, y in xy:
            roads_blob += struct.pack("<hh", x, y)

    names_offset = HEADER_SIZE
    roads_offset = names_offset + len(names_blob)
    index_offset = roads_offset + len(roads_blob)
    # RIDX road_ids = u16 → chỉ gắn index khi ≤65535; không thì app quét tuần tự
    if len(packed_roads) > 65535:
        index_blob = b""
    else:
        index_blob = _build_cell_index(
            origin_lat, origin_lon, packed_roads, roads_offset, cell_units)

    header = struct.pack(
        "<4sBBHiiiiIIIIII",
        MAGIC,
        VERSION,
        0,
        chunk_units & 0xFFFF,
        tile_cy,
        tile_cx,
        origin_lat,
        origin_lon,
        len(packed_roads),
        len(name_list),
        names_offset,
        roads_offset,
        index_offset if index_blob else 0,
        0,
    )
    assert len(header) == HEADER_SIZE, len(header)
    return bytes(header) + bytes(names_blob) + bytes(roads_blob) + bytes(index_blob)


def read_rmap_info(data):
    if not data or len(data) < HEADER_SIZE_V1:
        return None
    magic, ver, _res, chunk, cy, cx, o_lat, o_lon, n_roads, n_names, n_off, r_off = (
        struct.unpack_from("<4sBBHiiiiIIII", data, 0)
    )
    if magic != MAGIC or ver not in (VERSION_LEGACY, VERSION):
        return None
    index_off = 0
    if ver >= 2 and len(data) >= HEADER_SIZE:
        index_off = struct.unpack_from("<I", data, 40)[0]
    return {
        "version": ver,
        "chunk_units": chunk,
        "tile_cy": cy,
        "tile_cx": cx,
        "origin_lat": o_lat,
        "origin_lon": o_lon,
        "road_count": n_roads,
        "name_count": n_names,
        "names_offset": n_off,
        "roads_offset": r_off,
        "index_offset": index_off,
        "size": len(data),
        "crc": zlib.crc32(data) & 0xFFFFFFFF,
    }
