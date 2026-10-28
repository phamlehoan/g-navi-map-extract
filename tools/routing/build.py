#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OSM PBF → routing.bin hoặc tiles (g_*.rbin + routing_index.bin).

  out_pack/roads_map/<region>/routing.bin
  hoặc tiles: routing_index.bin + g_*.rbin

Usage:
  python routing.py vietnam.osm.pbf out_pack --mode regions --tiles --also hoangsa_truongsa.pbf
  python routing.py vietnam.osm.pbf out_pack --provinces "Ha Tinh,Da Nang,Quang Nam" --tiles
  python routing.py vietnam.osm.pbf out_dn/routing.bin --bbox 108.05,15.95,108.35,16.20
"""
from __future__ import print_function

import argparse
import os
import sys
import time
from collections import defaultdict

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from lib.common import add_common_args, ensure_osmium, resolve_bbox_and_pbfs
from routing.format import (
    FLAG_ALLEY,
    FLAG_DESTINATION,
    HW_CLASS,
    build_routing_bin,
    car_allowed,
    destination_only,
    haversine_m,
    is_alley_service,
    oneway_dir,
)
from routing.tiles import (
    DEFAULT_PAD_DEG,
    DEFAULT_TILE_DEG,
    split_graph_to_tiles,
)
from lib.vn_regions import REGIONS, VIET_NAM_ID
from lib.vn_provinces import mainland_provinces

ensure_osmium()
import osmium  # noqa: E402

INCLUDE_HIGHWAY = frozenset(HW_CLASS.keys())
SHAPE_STEP_M = 35.0
# Pad biên vùng để route gần ranh giới không đứt
REGION_PAD_DEG = 0.18
_META_ENABLED = True
_META_MAX_CLASS = 4
_ROUTING_MAX_CLASS = 9

PACK_PROFILES = {
    "full": {"routing_max_class": 9, "meta_max_class": 4},
    "hu_light": {"routing_max_class": 5, "meta_max_class": 3},
}


def _tags_dict(w):
    return {t.k: t.v for t in w.tags}


def _read_nodes(w):
    refs = []
    lls = []
    for n in w.nodes:
        if not n.location.valid():
            continue
        refs.append(n.ref)
        lls.append((n.location.lat, n.location.lon))
    return refs, lls


def _seg_crosses_bbox(la0, lo0, la1, lo1, min_lon, min_lat, max_lon, max_lat):
    """True nếu đoạn thẳng giao hình chữ nhật bbox (kể cả chỉ cắt cạnh)."""
    # Nhanh: AABB đoạn vs bbox
    if max(la0, la1) < min_lat or min(la0, la1) > max_lat:
        return False
    if max(lo0, lo1) < min_lon or min(lo0, lo1) > max_lon:
        return False
    # Một đầu trong
    if (min_lat <= la0 <= max_lat and min_lon <= lo0 <= max_lon) or (
            min_lat <= la1 <= max_lat and min_lon <= lo1 <= max_lon):
        return True
    # Liang-Barsky-ish: thử clip
    dx = la1 - la0
    dy = lo1 - lo0
    p = (-dx, dx, -dy, dy)
    q = (la0 - min_lat, max_lat - la0, lo0 - min_lon, max_lon - lo0)
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if abs(pi) < 1e-15:
            if qi < 0:
                return False
            continue
        t = qi / float(pi)
        if pi < 0:
            if t > u2:
                return False
            if t > u1:
                u1 = t
        else:
            if t < u1:
                return False
            if t < u2:
                u2 = t
    return True


def _way_ok(tags, bbox, lls):
    hw = tags.get("highway")
    if hw not in INCLUDE_HIGHWAY:
        return False
    cls = HW_CLASS.get(hw, 9)
    if cls > _ROUTING_MAX_CLASS:
        return False
    if not car_allowed(tags):
        return False
    if len(lls) < 2:
        return False
    if bbox is not None:
        min_lon, min_lat, max_lon, max_lat = bbox
        for la, lo in lls:
            if min_lat <= la <= max_lat and min_lon <= lo <= max_lon:
                return True
        # Đường cắt góc bbox mà không có node nằm trong — vẫn lấy
        for i in range(len(lls) - 1):
            la0, lo0 = lls[i]
            la1, lo1 = lls[i + 1]
            if _seg_crosses_bbox(la0, lo0, la1, lo1,
                                 min_lon, min_lat, max_lon, max_lat):
                return True
        return False
    return True


def decimate_shape(lls):
    if len(lls) <= 2:
        return list(lls)
    out = [lls[0]]
    acc = 0.0
    for i in range(1, len(lls) - 1):
        la0, lo0 = lls[i - 1]
        la1, lo1 = lls[i]
        acc += haversine_m(la0, lo0, la1, lo1)
        if acc >= SHAPE_STEP_M:
            out.append(lls[i])
            acc = 0.0
    out.append(lls[-1])
    return out


def pad_bbox(min_lon, min_lat, max_lon, max_lat, pad):
    return (min_lon - pad, min_lat - pad, max_lon + pad, max_lat + pad)


class DegreePass(osmium.SimpleHandler):
    def __init__(self, bbox):
        super(DegreePass, self).__init__()
        self.bbox = bbox
        self.degree = defaultdict(int)
        self.coords = {}
        self.n_ways = 0
        self.n_skip = 0
        self._t0 = time.time()
        self._last = self._t0

    def way(self, w):
        tags = _tags_dict(w)
        refs, lls = _read_nodes(w)
        if not _way_ok(tags, self.bbox, lls):
            if tags.get("highway") in INCLUDE_HIGHWAY and not car_allowed(tags):
                self.n_skip += 1
            return
        n = len(refs)
        for i, ref in enumerate(refs):
            self.coords[ref] = lls[i]
            if i == 0 or i == n - 1:
                self.degree[ref] += 2
            else:
                self.degree[ref] += 1
        self.n_ways += 1
        now = time.time()
        if now - self._last >= 25:
            self._last = now
            print("... pass1 ways=%d nodes=%d (%.0fs)" % (
                self.n_ways, len(self.coords), now - self._t0), flush=True)


class EdgePass(osmium.SimpleHandler):
    def __init__(self, bbox, degree, coords):
        super(EdgePass, self).__init__()
        self.bbox = bbox
        self.degree = degree
        self.coords = coords
        self.node_ids = []
        self.osm_to_idx = {}
        self.edges = []
        self.n_ways = 0
        self._t0 = time.time()
        self._last = self._t0

    def _ensure(self, ref):
        idx = self.osm_to_idx.get(ref)
        if idx is not None:
            return idx
        idx = len(self.node_ids)
        self.osm_to_idx[ref] = idx
        self.node_ids.append(ref)
        return idx

    def _is_junction(self, ref):
        # Mọi node đều là đỉnh graph. Lý do:
        #  - Công thức cũ `degree != 2` (giữa way +1, đầu/cuối +2) coi node nằm GIỮA
        #    2 way (1+1=2) là KHÔNG phải giao lộ → mất ~7% giao lộ (đo Đà Nẵng:
        #    933/12844) → không rẽ được, route vòng. Còn node giữa 1 way (=1) lại
        #    thành đỉnh → thực tế graph vốn đã gần như không nén.
        #  - App (OfflineRouter.nearestNode) snap GPS vào NODE gần nhất (55/140/800m):
        #    nén graph về chỉ giao lộ sẽ kéo điểm đi/đến về ngã tư xa, và cạnh dài
        #    vượt pad tile (tiles.py) bị bỏ. Muốn nén phải đổi app sang snap cạnh.
        return True

    def way(self, w):
        tags = _tags_dict(w)
        refs, lls = _read_nodes(w)
        if not _way_ok(tags, self.bbox, lls):
            return
        cls = HW_CLASS.get(tags.get("highway"), 5)
        flags = cls & 0x0F
        if destination_only(tags):
            flags |= FLAG_DESTINATION
        if is_alley_service(tags):
            flags |= FLAG_ALLEY
        direction = oneway_dir(tags)

        seg_start = 0
        n = len(refs)
        for i in range(1, n):
            end = (i == n - 1) or self._is_junction(refs[i])
            if not end:
                continue
            shape_raw = lls[seg_start:i + 1]
            if len(shape_raw) < 2:
                seg_start = i
                continue
            length = 0.0
            for j in range(len(shape_raw) - 1):
                la1, lo1 = shape_raw[j]
                la2, lo2 = shape_raw[j + 1]
                length += haversine_m(la1, lo1, la2, lo2)
            a_ref = refs[seg_start]
            b_ref = refs[i]
            if a_ref == b_ref or length < 0.5:
                seg_start = i
                continue
            ai = self._ensure(a_ref)
            bi = self._ensure(b_ref)
            shape = decimate_shape(shape_raw)
            shape_rev = list(reversed(shape))
            if direction == 1:
                self.edges.append((ai, bi, length, flags, shape))
            elif direction == -1:
                self.edges.append((bi, ai, length, flags, shape_rev))
            else:
                self.edges.append((ai, bi, length, flags, shape))
                self.edges.append((bi, ai, length, flags, shape_rev))
            seg_start = i

        self.n_ways += 1
        now = time.time()
        if now - self._last >= 25:
            self._last = now
            print("... pass2 ways=%d edges=%d nodes=%d (%.0fs)" % (
                self.n_ways, len(self.edges), len(self.node_ids),
                now - self._t0), flush=True)

    def nodes_ll(self):
        out = []
        for ref in self.node_ids:
            ll = self.coords.get(ref)
            out.append(ll if ll is not None else (0.0, 0.0))
        return out


def _apply_all(handler, pbfs):
    for pbf in pbfs:
        print("    file %s" % pbf, flush=True)
        handler.apply_file(pbf, locations=True)


def compile_one(pbfs, out_bin, bbox, label, tiles=False,
                tile_deg=DEFAULT_TILE_DEG, tile_pad=DEFAULT_PAD_DEG,
                enable_ch=False, enable_alt=False):
    if isinstance(pbfs, (str, bytes)):
        pbfs = [pbfs]
    t0 = time.time()
    print("==> [%s] bbox=%s tiles=%s" % (label, bbox, tiles), flush=True)
    print("==> Pass1", flush=True)
    p1 = DegreePass(bbox)
    _apply_all(p1, pbfs)
    print("==> Pass1 ways=%d nodes=%d skip=%d (%.0fs)" % (
        p1.n_ways, len(p1.coords), p1.n_skip, time.time() - t0), flush=True)
    if p1.n_ways == 0:
        print("==> SKIP empty region", label, flush=True)
        return False

    print("==> Pass2", flush=True)
    p2 = EdgePass(bbox, p1.degree, p1.coords)
    _apply_all(p2, pbfs)
    del p1.degree
    nodes_ll = p2.nodes_ll()
    edges = p2.edges
    print("==> graph nodes=%d edges=%d (%.0fs)" % (
        len(nodes_ll), len(edges), time.time() - t0), flush=True)

    out_dir = os.path.dirname(os.path.abspath(out_bin))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    if tiles:
        n = split_graph_to_tiles(
            nodes_ll, edges, out_dir,
            tile_deg=tile_deg, pad_deg=tile_pad)
        print("==> Tiles done n=%d in %.0fs" % (n, time.time() - t0), flush=True)
        if n > 0:
            _maybe_build_meta(out_dir, enable_ch=enable_ch, enable_alt=enable_alt)
        return n > 0

    data = build_routing_bin(nodes_ll, edges)
    with open(out_bin, "wb") as f:
        f.write(data)
    mb = len(data) / (1024 * 1024.0)
    print("==> Wrote %s (%.2f MB) in %.0fs" % (out_bin, mb, time.time() - t0), flush=True)
    return True


def _maybe_build_meta(region_dir, enable_ch=False, enable_alt=False):
    """Sau g_*.rbin → routing_meta.bin (long-haul OfflineRouter)."""
    if not _META_ENABLED:
        return
    try:
        from routing.meta import build_meta
    except ImportError:
        print("==> skip meta (thiếu routing/meta.py)", flush=True)
        return
    try:
        print("==> Building routing_meta.bin (max_class=%d)..." % _META_MAX_CLASS, flush=True)
        build_meta(region_dir, max_class=_META_MAX_CLASS)
    except SystemExit as e:
        print("==> meta skip:", e, flush=True)
        return
    except Exception as e:
        print("==> meta failed:", e, flush=True)
        return
    
    # Build acceleration structures
    if enable_alt or enable_ch:
        try:
            from routing.accel import build_accel
            print("==> Building acceleration structures (ALT=%s CH=%s)..." % (enable_alt, enable_ch), flush=True)
            build_accel(region_dir, landmarks=8, 
                       do_alt=enable_alt, do_ch=enable_ch, do_crp=False)
        except Exception as e:
            print("==> accel skip/failed:", e, flush=True)


def write_regions_manifest(roads_map_dir, written, provinces=False):
    """routing_regions.txt: danh sách vùng (hoặc tỉnh khi provinces=True) kèm bbox và có routing hay không."""
    path = os.path.join(roads_map_dir, "routing_regions.txt")
    if provinces:
        rows = [(p["id"], p["name"]) + tuple(p["bbox"]) for p in mainland_provinces()]
    else:
        rows = list(REGIONS)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# id\tlabel\tminLon\tminLat\tmaxLon\tmaxLat\thas_routing\n")
        for rid, label, min_lon, min_lat, max_lon, max_lat in rows:
            ok = "1" if rid in written else "0"
            f.write("%s\t%s\t%s\t%s\t%s\t%s\t%s\n" % (
                rid, label, min_lon, min_lat, max_lon, max_lat, ok))
    print("==> Manifest", path, flush=True)


def main():
    ap = argparse.ArgumentParser(description="OSM PBF → routing.bin / tiles")
    ap.add_argument("pbf", help="vietnam.osm.pbf")
    ap.add_argument("out", help="Thư mục pack (roads_map/…) hoặc file .bin")
    ap.add_argument("--mode", default="regions", choices=("regions", "provinces", "file"),
                    help="regions → roads_map/<id vùng>/… ; provinces → roads_map/<id tỉnh snake_case>/… "
                         "(34 tỉnh/thành sau sáp nhập); file → 1 file (+ --bbox/--provinces)")
    ap.add_argument("--tiles", action="store_true",
                    help="Cắt g_*.rbin + routing_index.bin (tránh OOM trên HU)")
    ap.add_argument("--tile-deg", type=float, default=DEFAULT_TILE_DEG,
                    help="Cạnh ô tile (độ), mặc định %.2f" % DEFAULT_TILE_DEG)
    ap.add_argument("--tile-pad", type=float, default=DEFAULT_PAD_DEG,
                    help="Pad chồng biên tile (độ), mặc định %.2f" % DEFAULT_PAD_DEG)
    ap.add_argument("--only", default=None,
                    help="Chỉ 1 region id (vd. bien_dong)")
    ap.add_argument("--no-meta", action="store_true",
                    help="Không build routing_meta.bin sau khi cắt tiles")
    ap.add_argument("--meta-max-class", type=int, default=4,
                    help="Class tối đa trong metagraph (mặc định 4=tertiary)")
    ap.add_argument("--pack-profile", choices=sorted(PACK_PROFILES.keys()),
                    default="full",
                    help="full=đủ kiệt; hu_light=bỏ residential+ (nhẹ HU)")
    ap.add_argument("--ch", action="store_true",
                    help="Build CH acceleration (Contraction Hierarchies) - fastest routing")
    ap.add_argument("--alt", action="store_true",
                    help="Build ALT landmarks - heuristic boost for A*")
    # pad mặc định lớn hơn cho routing (biên vùng)
    add_common_args(ap)
    # ghi đè pad mặc định common (0.05) → REGION_PAD_DEG
    for a in ap._actions:
        if a.dest == "pad":
            a.default = REGION_PAD_DEG
            break
    args = ap.parse_args()
    global _META_ENABLED, _META_MAX_CLASS, _ROUTING_MAX_CLASS
    _META_ENABLED = not args.no_meta
    prof = PACK_PROFILES[args.pack_profile]
    _ROUTING_MAX_CLASS = prof["routing_max_class"]
    if args.meta_max_class == 4 and args.pack_profile == "hu_light":
        _META_MAX_CLASS = prof["meta_max_class"]
    else:
        _META_MAX_CLASS = args.meta_max_class
    print("==> pack-profile=%s routing_max_class=%d meta_max_class=%d CH=%s ALT=%s" % (
        args.pack_profile, _ROUTING_MAX_CLASS, _META_MAX_CLASS, args.ch, args.alt), flush=True)

    bbox, pbfs, provinces = resolve_bbox_and_pbfs(args)

    # Chọn tỉnh / bbox tường minh → 1 graph (viet_nam hoặc file .bin)
    if provinces or args.provinces or args.mode == "file" or (
            bbox and args.out.lower().endswith(".bin")):
        if bbox is None:
            print("Cần --bbox hoặc --provinces", file=sys.stderr)
            sys.exit(1)
        if args.out.lower().endswith(".bin"):
            out_bin = args.out
        else:
            out_bin = os.path.join(args.out, "roads_map", VIET_NAM_ID, "routing.bin")
        label = "provinces" if provinces else "bbox"
        compile_one(pbfs, out_bin, bbox, label,
                    tiles=args.tiles, tile_deg=args.tile_deg, tile_pad=args.tile_pad,
                    enable_ch=args.ch, enable_alt=args.alt)
        print("==> Smart Sharing → tab Bản đồ → upload roads_map/%s/" % VIET_NAM_ID,
              flush=True)
        return

    roads_map = os.path.join(args.out, "roads_map")
    os.makedirs(roads_map, exist_ok=True)
    written = set()
    if args.mode == "provinces":
        todo = [(p["id"], p["name"]) + tuple(p["bbox"]) for p in mainland_provinces()]
    else:
        todo = list(REGIONS)
    for rid, label, min_lon, min_lat, max_lon, max_lat in todo:
        if args.only and args.only != rid:
            continue
        rb = pad_bbox(min_lon, min_lat, max_lon, max_lat, args.pad)
        out_bin = os.path.join(roads_map, rid, "routing.bin")
        print("\n======== %s ========" % rid, flush=True)
        if compile_one(pbfs, out_bin, rb, label,
                       tiles=args.tiles, tile_deg=args.tile_deg, tile_pad=args.tile_pad,
                       enable_ch=args.ch, enable_alt=args.alt):
            written.add(rid)
    write_regions_manifest(roads_map, written, provinces=(args.mode == "provinces"))
    print("\n==> Done %s: %s" % ("provinces" if args.mode == "provinces" else "regions",
                               ", ".join(sorted(written))), flush=True)
    print("    Smart Sharing → tab Bản đồ → upload từng thư mục %s trong roads_map/" % (
        "tỉnh" if args.mode == "provinces" else "vùng"), flush=True)


if __name__ == "__main__":
    main()
