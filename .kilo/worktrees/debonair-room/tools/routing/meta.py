#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gom skeleton đường lớn từ g_*.rbin → routing_meta.bin (GNR1 v2).

Metagraph kiểu Navitel-lite: chỉ class ≤ max_class (mặc định tertiary=4).
OfflineRouter dùng file này cho tuyến dài — A* trên đồ thị nhỏ thay vì merge
hàng trăm ô.

  python build_routing_meta.py path/to/region_dir
  python build_routing_meta.py path/to/region_dir --max-class 3

Output: region_dir/routing_meta.bin
"""
from __future__ import print_function

import argparse
import glob
import os
import struct
import sys
import time

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from routing.format import (
    CLASS_COST,
    HEADER_SIZE,
    MAGIC,
    VERSION,
    build_routing_bin,
    haversine_m,
    to_e7,
)

# Quantize ~0.5 m để gộp node biên ô
NODE_Q = 5
SHAPE_STEP_M = 80.0


def read_u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def read_i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def parse_gnr1(path):
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < HEADER_SIZE or data[0:4] != MAGIC:
        return None
    ver = data[4] & 0xFF
    if ver != VERSION:
        return None
    nc = read_u32(data, 8)
    ec = read_u32(data, 12)
    nodes_off = read_u32(data, 16)
    edges_off = read_u32(data, 20)
    adj_off = read_u32(data, 24)
    shapes_off = read_u32(data, 44)
    sidx_off = read_u32(data, 48)
    scount = read_u32(data, 52)
    if nc <= 0 or ec <= 0 or nc > 2_000_000:
        return None
    nodes = []
    for i in range(nc):
        o = nodes_off + i * 8
        la = read_i32(data, o)
        lo = read_i32(data, o + 4)
        nodes.append((la / 1e7, lo / 1e7, la, lo))
    edges = []
    for i in range(ec):
        o = edges_off + i * 8
        to = read_u32(data, o)
        lm = struct.unpack_from("<H", data, o + 4)[0]
        fl = struct.unpack_from("<H", data, o + 6)[0]
        edges.append((to, lm, fl))
    adj = [read_u32(data, adj_off + i * 4) for i in range(nc + 1)]
    shape_idx = [read_u32(data, sidx_off + i * 4) for i in range(ec + 1)]
    shapes = []
    for i in range(scount):
        o = shapes_off + i * 8
        shapes.append((read_i32(data, o) / 1e7, read_i32(data, o + 4) / 1e7))
    return {
        "nodes": nodes,
        "edges": edges,
        "adj": adj,
        "shape_idx": shape_idx,
        "shapes": shapes,
    }


def decimate_ll(lls, step_m=SHAPE_STEP_M):
    if len(lls) <= 2:
        return list(lls)
    out = [lls[0]]
    acc = 0.0
    for i in range(1, len(lls) - 1):
        la0, lo0 = lls[i - 1]
        la1, lo1 = lls[i]
        acc += haversine_m(la0, lo0, la1, lo1)
        if acc >= step_m:
            out.append(lls[i])
            acc = 0.0
    out.append(lls[-1])
    return out


def qkey(lat_e7, lon_e7):
    return (lat_e7 // NODE_Q, lon_e7 // NODE_Q)


def extract_meta_graph(nodes_ll, edges_full, max_class=4, simplify=True):
    """Extract metagraph từ full graph - chỉ giữ đường lớn.
    
    Args:
        nodes_ll: [(lat, lon), ...]
        edges_full: [(frm, to, length_m, flags, shape_ll), ...]
        max_class: Giữ highway class <= N (0=motorway … 4=tertiary)
        simplify: Rút gọn shape points
    
    Returns:
        (meta_nodes_ll, meta_edges_full) - filtered graph
    """
    print("Extracting metagraph max_class=%d..." % max_class, flush=True)
    t0 = time.time()
    
    # Map old node id -> new node id
    used_nodes = set()
    for frm, to, lm, fl, _ in edges_full:
        cls = fl & 0x0F
        if cls <= max_class:
            used_nodes.add(frm)
            used_nodes.add(to)
    
    old_to_new = {}
    meta_nodes = []
    for old_id in sorted(used_nodes):
        if old_id >= len(nodes_ll):
            continue
        old_to_new[old_id] = len(meta_nodes)
        meta_nodes.append(nodes_ll[old_id])
    
    # Filter edges
    meta_edges = []
    for frm, to, lm, fl, shape in edges_full:
        cls = fl & 0x0F
        if cls > max_class:
            continue
        new_frm = old_to_new.get(frm)
        new_to = old_to_new.get(to)
        if new_frm is None or new_to is None:
            continue
        if new_frm == new_to:
            continue
        
        # Simplify shape
        if simplify and shape and len(shape) > 2:
            shape = decimate_ll(shape, SHAPE_STEP_M)
        
        meta_edges.append((new_frm, new_to, lm, fl, shape))
    
    elapsed = time.time() - t0
    reduction_n = 100.0 * (1.0 - len(meta_nodes) / float(max(1, len(nodes_ll))))
    reduction_e = 100.0 * (1.0 - len(meta_edges) / float(max(1, len(edges_full))))
    
    print("Metagraph: %d nodes (%.1f%% reduction), %d edges (%.1f%% reduction) in %.1fs" % (
        len(meta_nodes), reduction_n, len(meta_edges), reduction_e, elapsed), flush=True)
    
    return meta_nodes, meta_edges


def build_meta(region_dir, max_class=4):
    pattern = os.path.join(region_dir, "g_*.rbin")
    files = sorted(glob.glob(pattern))
    if not files:
        raise SystemExit("No g_*.rbin in %s" % region_dir)

    # global_id -> (lat, lon)
    nodes_ll = []
    node_map = {}  # qkey -> gid

    def get_gid(lat, lon, lat_e7, lon_e7):
        k = qkey(lat_e7, lon_e7)
        gid = node_map.get(k)
        if gid is not None:
            return gid
        gid = len(nodes_ll)
        nodes_ll.append((lat, lon))
        node_map[k] = gid
        return gid

    edges_full = []
    seen_edge = set()
    t0 = time.time()
    n_files = 0
    n_kept = 0

    for path in files:
        g = parse_gnr1(path)
        n_files += 1
        if g is None:
            print("skip bad", os.path.basename(path), flush=True)
            continue
        local_gid = [None] * len(g["nodes"])
        for i, (la, lo, lae, loe) in enumerate(g["nodes"]):
            # Chỉ map node khi thật sự dùng (lazy) — nhưng cần trước edges
            pass
        for frm in range(len(g["nodes"])):
            e0 = g["adj"][frm]
            e1 = g["adj"][frm + 1]
            for e in range(e0, e1):
                to, lm, fl = g["edges"][e]
                cls = fl & 0x0F
                if cls > max_class:
                    continue
                if local_gid[frm] is None:
                    la, lo, lae, loe = g["nodes"][frm]
                    local_gid[frm] = get_gid(la, lo, lae, loe)
                if local_gid[to] is None:
                    la, lo, lae, loe = g["nodes"][to]
                    local_gid[to] = get_gid(la, lo, lae, loe)
                a = local_gid[frm]
                b = local_gid[to]
                if a == b:
                    continue
                # dedupe directed (a,b,cls)
                dk = (a, b, cls)
                if dk in seen_edge:
                    continue
                seen_edge.add(dk)
                s0 = g["shape_idx"][e]
                s1 = g["shape_idx"][e + 1]
                if s1 - s0 >= 2:
                    shape = decimate_ll(g["shapes"][s0:s1])
                else:
                    shape = [nodes_ll[a], nodes_ll[b]]
                edges_full.append((a, b, lm, fl, shape))
                n_kept += 1
        if n_files % 40 == 0:
            print("... tiles=%d/%d nodes=%d edges=%d (%.0fs)" % (
                n_files, len(files), len(nodes_ll), len(edges_full),
                time.time() - t0), flush=True)

    print("tiles=%d meta_nodes=%d meta_edges=%d max_class=%d (%.1fs)" % (
        n_files, len(nodes_ll), len(edges_full), max_class, time.time() - t0),
        flush=True)
    if len(nodes_ll) < 2 or len(edges_full) < 1:
        raise SystemExit("Metagraph empty — tăng --max-class?")

    blob = build_routing_bin(nodes_ll, edges_full)
    out = os.path.join(region_dir, "routing_meta.bin")
    with open(out, "wb") as f:
        f.write(blob)
    print("Wrote %s (%.1f MB)" % (out, len(blob) / (1024 * 1024.0)), flush=True)
    return out


def main():
    ap = argparse.ArgumentParser(description="Build routing_meta.bin from g_*.rbin")
    ap.add_argument("region_dir", help="Folder chứa routing_index.bin + g_*.rbin")
    ap.add_argument("--max-class", type=int, default=4,
                    help="Giữ highway class ≤ N (0=motorway … 4=tertiary). Default 4")
    args = ap.parse_args()
    if not os.path.isdir(args.region_dir):
        raise SystemExit("Not a dir: %s" % args.region_dir)
    build_meta(args.region_dir, max_class=args.max_class)


if __name__ == "__main__":
    main()
