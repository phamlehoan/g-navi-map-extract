#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helpers chung cho extract_map_tools."""
from __future__ import print_function

import argparse
import os
import sys

from lib.vn_provinces import (
    format_bbox,
    merge_bbox,
    needs_bien_dong_pbf,
    resolve_provinces,
)
from lib.vn_regions import DEFAULT_BIEN_DONG_PBF


def parse_bbox(s):
    parts = [float(x.strip()) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox = minLon,minLat,maxLon,maxLat")
    return tuple(parts)


def collect_pbfs(primary, also_list):
    out = []
    for p in [primary] + list(also_list or []):
        if not p:
            continue
        if not os.path.isfile(p):
            print("Missing PBF:", p, file=sys.stderr)
            sys.exit(1)
        if p not in out:
            out.append(p)
    return out


def resolve_bbox_and_pbfs(args, primary_attr="pbf"):
    """
    Từ --provinces / --bbox / --also → (bbox|None, pbfs, provinces).
    Tự thêm hoangsa_truongsa.pbf nếu chọn Biển Đông và file tồn tại cạnh PBF chính.
    """
    provinces = []
    unknown = []
    if getattr(args, "provinces", None):
        provinces, unknown = resolve_provinces(args.provinces)
        if unknown:
            print("Không nhận tỉnh:", ", ".join(unknown), file=sys.stderr)
            sys.exit(1)
        if not provinces:
            print("Chưa chọn tỉnh nào.", file=sys.stderr)
            sys.exit(1)

    bbox = None
    if getattr(args, "bbox", None):
        bbox = parse_bbox(args.bbox)
    elif provinces:
        pad = float(getattr(args, "pad", 0.05) or 0.05)
        bbox = merge_bbox(provinces, pad=pad)

    also = list(getattr(args, "also", None) or [])
    primary = getattr(args, primary_attr)
    if provinces and needs_bien_dong_pbf(provinces):
        # thử cạnh PBF chính
        base = os.path.dirname(os.path.abspath(primary)) or "."
        candidate = os.path.join(base, DEFAULT_BIEN_DONG_PBF)
        if os.path.isfile(candidate) and candidate not in also:
            also.append(candidate)
            print("==> Tự thêm", candidate, "(Biển Đông)", flush=True)
        elif not any(DEFAULT_BIEN_DONG_PBF in (a or "") for a in also):
            print("CẢNH BÁO: chọn Biển Đông nhưng chưa có %s — thêm --also" %
                  DEFAULT_BIEN_DONG_PBF, file=sys.stderr)

    pbfs = collect_pbfs(primary, also)
    if provinces:
        names = ", ".join(p["name"] for p in provinces)
        print("==> Tỉnh: %s" % names, flush=True)
        print("==> BBox: %s" % format_bbox(bbox), flush=True)
    elif bbox:
        print("==> BBox: %s" % format_bbox(bbox), flush=True)
    return bbox, pbfs, provinces


def add_common_args(ap, with_provinces=True, with_bbox=True, with_also=True):
    if with_bbox:
        ap.add_argument("--bbox", default=None,
                        help="minLon,minLat,maxLon,maxLat (ghi đè --provinces)")
    if with_provinces:
        ap.add_argument(
            "--provinces", default=None,
            help='Danh sách tỉnh, vd: "Ha Tinh,Quang Binh,Da Nang,Quang Nam"')
        ap.add_argument("--pad", type=float, default=0.5,
                        help="Pad độ quanh union bbox tỉnh (mặc định 0.5 ~55km)")
    if with_also:
        ap.add_argument("--also", action="append", default=[],
                        help="PBF bổ sung (vd. hoangsa_truongsa.pbf)")
    return ap


def ensure_osmium():
    try:
        import osmium  # noqa: F401
    except ImportError:
        print("Cần osmium: pip install osmium", file=sys.stderr)
        print("Hoặc dùng Docker: docker build -t gnavi-extract ./extract_map_tools",
              file=sys.stderr)
        sys.exit(1)
