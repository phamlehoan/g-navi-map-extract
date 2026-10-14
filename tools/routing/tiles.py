#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Routing tiles: cắt graph → g_{cy}_{cx}.rbin + routing_index.bin.

Index (little-endian):
  0  magic          b'GRIX'
  4  version        u8 (=1)
  5  reserved       u8
  6  flags          u16
  8  scale          u32   # 100000
 12  tile_units     u32   # vd. 20000 = 0.2°
 16  pad_units      u32
 20  tile_count     u32
 24  reserved2      u32
 28… entries[tile_count]:
     cy i32, cx i32, node_count u32, edge_count u32, bytes u32
"""
from __future__ import print_function

import os
import struct

from routing.format import build_routing_bin, to_e7

INDEX_MAGIC = b"GRIX"
INDEX_VERSION = 1
INDEX_HEADER = 28
INDEX_ENTRY = 20  # 2*i32 + 3*u32
# Khớp GNR1: lat/lon * 1e7
SCALE = 10000000
DEFAULT_TILE_DEG = 0.20
DEFAULT_PAD_DEG = 0.05


def div_floor(a, b):
    if b <= 0:
        raise ValueError("b")
    if a >= 0:
        return a // b
    return -((-a + b - 1) // b)


def tile_of_e7(lat_e7, lon_e7, tile_units):
    return div_floor(lat_e7, tile_units), div_floor(lon_e7, tile_units)


def write_routing_index(path, tile_units, pad_units, entries):
    """entries: list of (cy, cx, node_count, edge_count, bytes)."""
    with open(path, "wb") as f:
        # 4s + B + B + H + 5*I = 28 bytes
        f.write(struct.pack(
            "<4sBBHIIIII",
            INDEX_MAGIC,
            INDEX_VERSION,
            0,
            0,
            SCALE,
            tile_units,
            pad_units,
            len(entries),
            0,
        ))
        for cy, cx, nc, ec, nbytes in entries:
            f.write(struct.pack("<iiIII", cy, cx, nc, ec, nbytes))


def split_graph_to_tiles(nodes_ll, edges_full, out_dir,
                         tile_deg=DEFAULT_TILE_DEG, pad_deg=DEFAULT_PAD_DEG):
    """
    nodes_ll: [(lat,lon), ...]
    edges_full: [(frm, to, length_m, flags, shape_ll), ...]
    → ghi g_{cy}_{cx}.rbin + routing_index.bin vào out_dir
    """
    if not nodes_ll:
        return 0
    os.makedirs(out_dir, exist_ok=True)
    tile_u = int(round(tile_deg * SCALE))
    pad_u = int(round(pad_deg * SCALE))
    if tile_u < 100000:  # tối thiểu ~0.01°
        tile_u = 100000

    lat_e7 = [to_e7(la) for la, _ in nodes_ll]
    lon_e7 = [to_e7(lo) for _, lo in nodes_ll]

    # Tập tile phủ mọi node (ô core)
    tiles = set()
    for i in range(len(nodes_ll)):
        tiles.add(tile_of_e7(lat_e7[i], lon_e7[i], tile_u))

    # Với mỗi tile: node nằm trong core∪pad
    def in_pad(i, cy, cx):
        tlat0 = cy * tile_u
        tlon0 = cx * tile_u
        la = lat_e7[i]
        lo = lon_e7[i]
        return (la >= tlat0 - pad_u and la < tlat0 + tile_u + pad_u
                and lo >= tlon0 - pad_u and lo < tlon0 + tile_u + pad_u)

    # Chia node/cạnh vào tile MỘT lần (bản cũ: mỗi tile quét lại toàn bộ N+E →
    # O(tiles×(N+E)), cả nước rất lâu). Kết quả giữ nguyên: node theo thứ tự
    # global tăng dần, cạnh theo thứ tự edges_full.
    pad_tiles = {}   # (cy,cx) -> [global node idx...]
    for gi in range(len(nodes_ll)):
        la = lat_e7[gi]
        lo = lon_e7[gi]
        for cy in range(div_floor(la - pad_u, tile_u), div_floor(la + pad_u, tile_u) + 1):
            for cx in range(div_floor(lo - pad_u, tile_u), div_floor(lo + pad_u, tile_u) + 1):
                if (cy, cx) in tiles and in_pad(gi, cy, cx):
                    pad_tiles.setdefault((cy, cx), []).append(gi)
    core_edges = {}  # (cy,cx) -> [edge idx...]
    for ei, e in enumerate(edges_full):
        t1 = tile_of_e7(lat_e7[e[0]], lon_e7[e[0]], tile_u)
        t2 = tile_of_e7(lat_e7[e[1]], lon_e7[e[1]], tile_u)
        core_edges.setdefault(t1, []).append(ei)
        if t2 != t1:
            core_edges.setdefault(t2, []).append(ei)

    entries = []
    written = 0
    for cy, cx in sorted(tiles):
        local_ids = pad_tiles.get((cy, cx), [])
        if len(local_ids) < 2:
            continue
        global_to_local = {gi: li for li, gi in enumerate(local_ids)}

        local_nodes = [nodes_ll[gi] for gi in local_ids]
        local_edges = []
        for ei in core_edges.get((cy, cx), ()):
            frm, to, length_m, flags, shape = edges_full[ei]
            # chỉ lấy cạnh chạm core; pad chỉ để nối
            lf = global_to_local.get(frm)
            lt = global_to_local.get(to)
            if lf is None or lt is None:
                continue
            local_edges.append((lf, lt, length_m, flags, shape))
        if not local_edges:
            continue

        data = build_routing_bin(local_nodes, local_edges)
        name = "g_%d_%d.rbin" % (cy, cx)
        path = os.path.join(out_dir, name)
        with open(path, "wb") as f:
            f.write(data)
        nc = struct.unpack_from("<I", data, 8)[0]
        ec = struct.unpack_from("<I", data, 12)[0]
        entries.append((cy, cx, nc, ec, len(data)))
        written += 1
        if written % 50 == 0:
            print("... tiles written %d" % written, flush=True)

    idx_path = os.path.join(out_dir, "routing_index.bin")
    write_routing_index(idx_path, tile_u, pad_u, entries)
    legacy = os.path.join(out_dir, "routing.bin")
    if os.path.isfile(legacy):
        try:
            os.remove(legacy)
            print("==> Removed legacy routing.bin (dùng tiles)", flush=True)
        except Exception:
            pass
    print("==> Tiles %d -> %s (index %s)" % (written, out_dir, idx_path), flush=True)
    return written
