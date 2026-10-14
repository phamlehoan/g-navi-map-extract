#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Format routing.bin (GNavi offline router) — graph có hướng + polyline cạnh.

Layout little-endian, version 2 — CSR adjacency + shape points từng edge.

HEADER 64 bytes
  0  magic           b'GNR1'
  4  version         u8 (=2)
  5  reserved        u8
  6  flags           u16
  8  node_count      u32
 12  edge_count      u32
 16  nodes_offset    u32   # Node[node_count] 8B
 20  edges_offset    u32   # Edge[edge_count] 8B
 24  adj_offset      u32   # u32[node_count+1]
 28  min_lat_e7      i32
 32  min_lon_e7      i32
 36  max_lat_e7      i32
 40  max_lon_e7      i32
 44  shapes_offset   u32   # ShapePoint[n] : lat_e7 i32, lon_e7 i32
 48  shape_idx_off   u32   # u32[edge_count+1] — CSR vào shapes
 52  shape_count     u32
 56  grid_offset     u32   # 0 = app tự buildGrid; else GGRD section
 60  grid_bytes      u32

Node 8B: lat_e7 i32, lon_e7 i32
Edge 8B: to_node u32, length_m u16, flags u16
  flags bits 0..3 = highway class
  bit 4 = destination_only
  bit 5 = alley / driveway / parking_aisle (cost cao, tránh cắt qua)

Shape của edge e: points[shape_idx[e] .. shape_idx[e+1]) gồm cả endpoint
(from → … → to). Khi vẽ tuyến: mỗi edge bỏ điểm đầu (trùng node trước).

GGRD @ grid_offset (nhúng index snap node — khớp OfflineRouter GRID=200):
  0  magic     b'GGRD'
  4  version   u8 (=1)
  5  reserved  u8
  6  grid_n    u16 (=200)
  8  min_lat_e7 i32
 12  min_lon_e7 i32
 16  max_lat_e7 i32
 20  max_lon_e7 i32
 24  u32 cell_off[grid_n*grid_n + 1]   # CSR index vào node_ids
     u32 node_ids[]                    # node index per cell
"""
from __future__ import print_function

import struct

MAGIC = b"GNR1"
VERSION = 2
HEADER_SIZE = 64
NODE_SIZE = 8
EDGE_SIZE = 8
SHAPE_PT_SIZE = 8
GRID_N = 200
GGRD_MAGIC = b"GGRD"
GGRD_VERSION = 1
GGRD_HEADER = 24

HW_CLASS = {
    "motorway": 0, "motorway_link": 0,
    "trunk": 1, "trunk_link": 1,
    "primary": 2, "primary_link": 2,
    "secondary": 3, "secondary_link": 3,
    "tertiary": 4, "tertiary_link": 4,
    "unclassified": 5, "road": 5,
    "residential": 6,
    "living_street": 7,
    "service": 8,
    "track": 9,
}

# cost multiplier (cao = chậm / kém ưu tiên)
CLASS_COST = (0.70, 0.75, 0.85, 0.95, 1.00, 1.12, 1.25, 1.45, 1.85, 2.40)

FLAG_DESTINATION = 1 << 4
FLAG_ALLEY = 1 << 5


def to_e7(v):
    return int(round(v * 1e7))


def haversine_m(lat1, lon1, lat2, lon2):
    import math
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def car_allowed(tags):
    hw = tags.get("highway", "")
    if hw == "construction" or hw == "proposed":
        return False
    if tags.get("area") in ("yes", "true", "1"):
        return False
    for k in ("motorcar", "motor_vehicle", "vehicle"):
        v = (tags.get(k) or "").lower()
        if v in ("no", "private", "agricultural", "forestry", "military", "emergency"):
            return False
    acc = (tags.get("access") or "").lower()
    if acc in ("no", "private", "agricultural", "forestry", "military"):
        return False
    return True


def destination_only(tags):
    for k in ("motorcar", "motor_vehicle", "vehicle", "access"):
        v = (tags.get(k) or "").lower()
        if v == "destination" or v == "customers":
            return True
    return False


def is_alley_service(tags):
    """Hẻm / kiệt / lối vào — không dùng làm đường cắt."""
    hw = tags.get("highway", "")
    svc = (tags.get("service") or "").lower()
    if hw == "service" and svc in (
            "alley", "driveway", "parking_aisle", "emergency_access"):
        return True
    # Tên VN thường gặp (bỏ chữ Trung — không dùng làm tín hiệu alley)
    from lib.osm_names import road_name
    name = (road_name(tags) or "").lower()
    for tip in ("kiet", "kiệt", "hem", "hẻm", "ngo ", "ngõ "):
        if tip in name:
            return True
    return False


def oneway_dir(tags):
    ow = (tags.get("oneway") or "").lower()
    if ow in ("yes", "true", "1"):
        return 1
    if ow in ("-1", "reverse"):
        return -1
    if ow in ("no", "false", "0"):
        return 0
    hw = tags.get("highway", "")
    if hw in ("motorway", "motorway_link") or tags.get("junction") == "roundabout":
        return 1
    if (tags.get("oneway:motor_vehicle") or "").lower() in ("yes", "true", "1"):
        return 1
    return 0


def _build_node_grid(nodes_ll, min_lat, min_lon, max_lat, max_lon, grid_n=GRID_N):
    """GGRD blob — CSR node ids theo lưới đều trên bbox e7."""
    n = len(nodes_ll)
    if n <= 0:
        return b""
    min_la = float(min_lat) / 1e7
    min_lo = float(min_lon) / 1e7
    max_la = float(max_lat) / 1e7
    max_lo = float(max_lon) / 1e7
    cell_lat = max(1e-6, (max_la - min_la) / float(grid_n))
    cell_lon = max(1e-6, (max_lo - min_lo) / float(grid_n))
    n_cells = grid_n * grid_n
    buckets = [[] for _ in range(n_cells)]
    for i, (lat, lon) in enumerate(nodes_ll):
        gy = int((lat - min_la) / cell_lat)
        gx = int((lon - min_lo) / cell_lon)
        if gy < 0:
            gy = 0
        if gx < 0:
            gx = 0
        if gy >= grid_n:
            gy = grid_n - 1
        if gx >= grid_n:
            gx = grid_n - 1
        buckets[gy * grid_n + gx].append(i)
    cell_off = [0]
    node_ids = []
    for b in buckets:
        node_ids.extend(b)
        cell_off.append(len(node_ids))
    blob = bytearray()
    blob += struct.pack(
        "<4sBBHiiii",
        GGRD_MAGIC,
        GGRD_VERSION,
        0,
        grid_n & 0xFFFF,
        int(min_lat),
        int(min_lon),
        int(max_lat),
        int(max_lon),
    )
    assert len(blob) == GGRD_HEADER
    for off in cell_off:
        blob += struct.pack("<I", off)
    for nid in node_ids:
        blob += struct.pack("<I", nid)
    return bytes(blob)


def build_routing_bin(nodes_ll, edges_full):
    """
    nodes_ll: list[(lat, lon)]
    edges_full: list[(frm, to, length_m, flags, shape_ll)]
      shape_ll = [(lat,lon), ...] from→to inclusive (≥2)
    """
    n = len(nodes_ll)
    buckets = [[] for _ in range(n)]
    for frm, to, length_m, flags, shape in edges_full:
        if frm < 0 or frm >= n or to < 0 or to >= n:
            continue
        lm = int(length_m)
        if lm < 1:
            lm = 1
        if lm > 65535:
            lm = 65535
        if not shape or len(shape) < 2:
            shape = [nodes_ll[frm], nodes_ll[to]]
        buckets[frm].append((to, lm, flags & 0xFFFF, shape))

    edge_blob = bytearray()
    shape_blob = bytearray()
    shape_idx = []
    adj = [0] * (n + 1)
    ecount = 0
    scount = 0
    for i in range(n):
        adj[i] = ecount
        for to, lm, fl, shape in buckets[i]:
            shape_idx.append(scount)
            for la, lo in shape:
                shape_blob += struct.pack("<ii", to_e7(la), to_e7(lo))
                scount += 1
            edge_blob += struct.pack("<IHH", to, lm, fl)
            ecount += 1
    adj[n] = ecount
    shape_idx.append(scount)

    node_blob = bytearray()
    min_lat = 90 * 1e7
    min_lon = 180 * 1e7
    max_lat = -90 * 1e7
    max_lon = -180 * 1e7
    for lat, lon in nodes_ll:
        la = to_e7(lat)
        lo = to_e7(lon)
        node_blob += struct.pack("<ii", la, lo)
        if la < min_lat:
            min_lat = la
        if la > max_lat:
            max_lat = la
        if lo < min_lon:
            min_lon = lo
        if lo > max_lon:
            max_lon = lo

    adj_blob = bytearray()
    for a in adj:
        adj_blob += struct.pack("<I", a)

    sidx_blob = bytearray()
    for a in shape_idx:
        sidx_blob += struct.pack("<I", a)

    nodes_off = HEADER_SIZE
    edges_off = nodes_off + len(node_blob)
    adj_off = edges_off + len(edge_blob)
    shapes_off = adj_off + len(adj_blob)
    sidx_off = shapes_off + len(shape_blob)
    grid_off = sidx_off + len(sidx_blob)
    grid_blob = _build_node_grid(
        nodes_ll, int(min_lat), int(min_lon), int(max_lat), int(max_lon))
    grid_bytes = len(grid_blob)

    # 4sBBH(8) + 5*I(20) + 4*i(16) + 5*I(20) = 64
    header = struct.pack(
        "<4sBBH" + "I" * 5 + "i" * 4 + "I" * 5,
        MAGIC,
        VERSION,
        0,
        0,
        n,
        ecount,
        nodes_off,
        edges_off,
        adj_off,
        int(min_lat),
        int(min_lon),
        int(max_lat),
        int(max_lon),
        shapes_off,
        sidx_off,
        scount,
        grid_off if grid_bytes else 0,
        grid_bytes,
    )
    assert len(header) == HEADER_SIZE, len(header)
    return bytes(
        header + node_blob + edge_blob + adj_blob + shape_blob + sidx_blob + grid_blob
    )


def edge_cost_m(length_m, flags):
    cls = flags & 0x0F
    if cls >= len(CLASS_COST):
        cls = len(CLASS_COST) - 1
    c = length_m * CLASS_COST[cls]
    if flags & FLAG_DESTINATION:
        c *= 3.0
    if flags & FLAG_ALLEY:
        c *= 2.8  # tránh cắt qua kiệt khi còn đường lớn
    return c
