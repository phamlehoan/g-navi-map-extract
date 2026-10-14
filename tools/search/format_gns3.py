#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GNS3 search.bin format for OfflineGeocoder (GNavi).

Magic: GNS3, Version: 1, Header: 96 bytes.

Record layouts (little-endian, must match OfflineGeocoder.java):
  StreetRec 28B: name_id u32, norm_name_id u32, lat_e7 i32, lon_e7 i32,
                 housesOff u32 (entry index), housesCount u16, pad 6
  HouseEntry 12B: num u16, pad u16, lat_e7 i32, lon_e7 i32
  HouseGlobal 16B: street_idx u32, num u16, pad u16, lat_e7 i32, lon_e7 i32
  Admin/POI 16B: name_id u32, lat_e7 i32, lon_e7 i32, level/cat u8, pad 3
  TokenRec 16B: key_off u32, key_len u16, pad u16, post_off u32, post_count u32
"""
from __future__ import print_function

import re
import struct
import unicodedata
from collections import defaultdict

MAGIC = b"GNS3"
VERSION = 1
HEADER_SIZE = 96

STREET_SZ = 28
HOUSE_ENTRY_SZ = 12
HOUSE_GLOBAL_SZ = 16
ADMIN_SZ = 16
POI_SZ = 16
TOKEN_SZ = 16
NORM_IDX_SZ = 8
GRID_CELL_SZ = 12

# Grid parameters (must match OfflineGeocoder.java)
GRID_CELL_DEG = 0.05
GRID_LAT0 = 8.0
GRID_LON0 = 102.0

# Posting types — 2 bits (must match OfflineGeocoder)
TYPE_POI = 0
TYPE_STREET = 1
TYPE_ADDR = 2
TYPE_ADMIN = 3

PLACE_LEVEL = {
    "city": 4, "town": 5, "municipality": 5, "suburb": 6,
    "borough": 6, "district": 6, "village": 7, "hamlet": 8,
    "neighbourhood": 8, "quarter": 8, "city_block": 9,
}


def normalize_vi(text):
    if not text:
        return ""
    s = text.strip().lower()
    for prefix in ("đường ", "duong ", "phố ", "pho ", "ngõ ", "ngo ",
                   "hẻm ", "hem ", "quốc lộ ", "quoc lo ", "tỉnh lộ ", "tinh lo "):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "d")
    s = re.sub(r"[^a-z0-9/]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokenize(norm):
    if not norm:
        return []
    return [p for p in norm.split() if p]


_HOUSE_RE = re.compile(r"^(\d{1,5}[a-z]?(?:[/-]\d{1,5}[a-z]?)?)$", re.I)


def is_house_token(tok):
    return bool(_HOUSE_RE.match(tok or ""))


def parse_query(raw):
    norm = normalize_vi(raw)
    toks = tokenize(norm)
    house = None
    text = []
    for t in toks:
        if house is None and is_house_token(t):
            house = t
        else:
            text.append(t)
    return house, text, norm


def pack_id(typ, index):
    return ((typ & 3) << 30) | (index & 0x3FFFFFFF)


def unpack_id(pid):
    return (pid >> 30) & 3, pid & 0x3FFFFFFF


def to_e7(v):
    return int(round(v * 1e7))


def _grid_cell_id(lat, lon):
    """Calculate grid cell ID (must match OfflineGeocoder.cellId)."""
    # Grid coordinates relative to origin
    iy = int((lat - GRID_LAT0) / GRID_CELL_DEG)
    ix = int((lon - GRID_LON0) / GRID_CELL_DEG)

    # Clamp to valid range
    if iy < -32768:
        iy = -32768
    if iy > 32767:
        iy = 32767
    if ix < 0:
        ix = 0
    if ix > 65535:
        ix = 65535

    # Pack: ((iy & 0xFFFF) << 16) | (ix & 0xFFFF)
    return ((iy & 0xFFFF) << 16) | (ix & 0xFFFF)


def _house_num_u16(house_str):
    """Leading digits → u16 for HouseEntry / HouseGlobal."""
    if house_str is None:
        return 0
    m = re.match(r"(\d+)", str(house_str).strip())
    if not m:
        return 0
    n = int(m.group(1))
    if n < 0:
        return 0
    if n > 65535:
        return 65535
    return n


def _ensure_name(names, name_to_id, display):
    if display in name_to_id:
        return name_to_id[display]
    i = len(names)
    names.append(display)
    name_to_id[display] = i
    return i


def _add_tokens(token_map, norm_text, typ, index):
    toks = tokenize(norm_text)
    if not toks:
        return
    pid = pack_id(typ, index)
    for tok in toks:
        token_map.setdefault(tok, []).append(pid)
    for i in range(len(toks) - 1):
        bigram = toks[i] + " " + toks[i + 1]
        token_map.setdefault(bigram, []).append(pid)


def build_search_bin(names, streets, addrs, admins, token_map, pois=None):
    """
    Build GNS3 search.bin format.
    Args:
        names: list[str] display names (mutated: may append norm strings)
        streets: list[(name_id, lat, lon, norm_name, houses)]
            houses: list[(house_num_or_str, lat, lon)] or
                    list[(house_num_or_str, lat, lon, house_str)]
        addrs: list[(name_id, house_str, lat, lon, flags)]  # orphan / all addr points
        admins: list[(name_id, lat, lon, level)]
        token_map: dict[str, list[packed_id]] or None (auto-build)
        pois: list[(name_id, lat, lon, category)] optional
    """
    if pois is None:
        pois = []
    names = list(names)  # copy — we may append norm names
    name_to_id = {nm: i for i, nm in enumerate(names)}

    # Street rows + attach orphan addrs to nearest street with same name_id
    street_rows = []  # dicts
    by_name = defaultdict(list)
    for name_id, lat, lon, norm_name, houses in streets:
        display = names[name_id] if 0 <= name_id < len(names) else ""
        norm = normalize_vi(norm_name) if norm_name else normalize_vi(display)
        # norm_name_id must be an index into the names pool (OfflineGeocoder.readName)
        norm_id = _ensure_name(names, name_to_id, norm) if norm else name_id
        hs = []
        for h in (houses or []):
            if len(h) >= 4:
                num_raw, h_lat, h_lon, h_str = h[0], h[1], h[2], h[3]
            else:
                num_raw, h_lat, h_lon = h[0], h[1], h[2]
                h_str = str(num_raw)
            hs.append((_house_num_u16(num_raw), float(h_lat), float(h_lon),
                       normalize_vi(str(h_str)).replace(" ", "") or str(num_raw)))
        row = {
            "name_id": name_id,
            "norm_id": norm_id,
            "lat": float(lat),
            "lon": float(lon),
            "houses": hs,
        }
        by_name[name_id].append(len(street_rows))
        street_rows.append(row)

    orphan_addrs = []
    for name_id, house_str, lat, lon, _flags in addrs:
        hn = normalize_vi(house_str).replace(" ", "") or str(house_str).lower()
        num = _house_num_u16(hn)
        cands = by_name.get(name_id)
        if not cands:
            orphan_addrs.append((0xFFFFFFFF, num, float(lat), float(lon), hn))
            continue
        best_i = cands[0]
        best_d = None
        for si in cands:
            s = street_rows[si]
            dy = lat - s["lat"]
            dx = (lon - s["lon"]) * 0.85  # rough lon shrink near VN
            d = dy * dy + dx * dx
            if best_d is None or d < best_d:
                best_d = d
                best_i = si
        street_rows[best_i]["houses"].append((num, float(lat), float(lon), hn))

    # Sort houses per street (binary search in OfflineGeocoder)
    for row in street_rows:
        row["houses"].sort(key=lambda x: x[0])

    # housesBlob + houseGlobal
    houses_blob = bytearray()
    house_global = bytearray()
    street_houses_off = []
    street_houses_count = []
    # (house_str → list of house_global indices) for TYPE_ADDR tokens
    addr_token_hits = defaultdict(list)

    def _pack_house_entry(num, lat_e7, lon_e7):
        return struct.pack("<HHii", num & 0xFFFF, 0, lat_e7, lon_e7)

    def _pack_house_global(street_idx, num, lat_e7, lon_e7):
        return struct.pack("<IHHii", street_idx & 0xFFFFFFFF, num & 0xFFFF, 0,
                           lat_e7, lon_e7)

    for s_idx, row in enumerate(street_rows):
        entry_off = len(houses_blob) // HOUSE_ENTRY_SZ
        street_houses_off.append(entry_off)
        hs = row["houses"]
        street_houses_count.append(len(hs))
        for num, h_lat, h_lon, h_str in hs:
            lat_e7, lon_e7 = to_e7(h_lat), to_e7(h_lon)
            houses_blob += _pack_house_entry(num, lat_e7, lon_e7)
            gi = len(house_global) // HOUSE_GLOBAL_SZ
            house_global += _pack_house_global(s_idx, num, lat_e7, lon_e7)
            if h_str:
                addr_token_hits[h_str].append(gi)

    for street_idx, num, lat, lon, h_str in orphan_addrs:
        lat_e7, lon_e7 = to_e7(lat), to_e7(lon)
        gi = len(house_global) // HOUSE_GLOBAL_SZ
        house_global += _pack_house_global(street_idx, num, lat_e7, lon_e7)
        if h_str:
            addr_token_hits[h_str].append(gi)

    # Admin / POI blobs
    admins_blob = bytearray()
    for name_id, lat, lon, level in admins:
        admins_blob += struct.pack("<IiiB3x", name_id, to_e7(lat), to_e7(lon),
                                   level & 0xFF)

    pois_blob = bytearray()
    for name_id, lat, lon, category in pois:
        pois_blob += struct.pack("<IiiB3x", name_id, to_e7(lat), to_e7(lon),
                                 category & 0xFF)

    # Token index: street_idx / house_global_idx / admin_idx / poi_idx
    if token_map is None:
        token_map = {}
    else:
        token_map = dict(token_map)

    for s_idx, row in enumerate(street_rows):
        display = names[row["name_id"]] if 0 <= row["name_id"] < len(names) else ""
        norm = normalize_vi(display)
        _add_tokens(token_map, norm, TYPE_STREET, s_idx)

    for h_str, gis in addr_token_hits.items():
        for gi in gis:
            token_map.setdefault(h_str, []).append(pack_id(TYPE_ADDR, gi))

    for a_idx, (name_id, lat, lon, level) in enumerate(admins):
        if 0 <= name_id < len(names):
            _add_tokens(token_map, normalize_vi(names[name_id]), TYPE_ADMIN, a_idx)

    for p_idx, (name_id, lat, lon, category) in enumerate(pois):
        if 0 <= name_id < len(names):
            _add_tokens(token_map, normalize_vi(names[name_id]), TYPE_POI, p_idx)

    # Build spatial grid index for streets
    grid_cells = defaultdict(list)  # cell_id -> list of street indices
    for s_idx, row in enumerate(street_rows):
        cell_id = _grid_cell_id(row["lat"], row["lon"])
        grid_cells[cell_id].append(s_idx)

    # Sort grid cells by cell_id and build grid index + postings
    grid_items = sorted(grid_cells.items())
    grid_index = bytearray()
    grid_postings = bytearray()
    for cell_id, street_indices in grid_items:
        post_off = len(grid_postings) // 4
        # Limit postings per cell to avoid huge cells
        count = len(street_indices)
        if count > 5000:
            count = 5000
            street_indices = street_indices[:5000]
        for s_idx in street_indices:
            grid_postings += struct.pack("<I", s_idx & 0xFFFFFFFF)
        grid_index += struct.pack("<III", cell_id & 0xFFFFFFFF, post_off & 0xFFFFFFFF, count & 0xFFFFFFFF)

    token_items = sorted(token_map.items(), key=lambda kv: kv[0])
    keys_blob = bytearray()
    postings_blob = bytearray()
    token_recs = bytearray()

    for key, ids in token_items:
        uniq = sorted(set(ids))
        key_raw = key.encode("utf-8")
        if len(key_raw) > 65535:
            key_raw = key_raw[:65535]
        key_off = len(keys_blob)
        keys_blob += key_raw
        post_off = len(postings_blob)
        for pid in uniq:
            postings_blob += struct.pack("<I", pid & 0xFFFFFFFF)
        token_recs += struct.pack("<IHHII",
                                  key_off, len(key_raw), 0, post_off, len(uniq))

    # Norm index unused by current OfflineGeocoder — keep empty
    norm_index = bytearray()

    # Names blob
    names_blob = bytearray()
    name_offsets = []
    for nm in names:
        raw = (nm or "").encode("utf-8")
        if len(raw) > 65535:
            raw = raw[:65535]
        name_offsets.append(len(names_blob))
        names_blob += struct.pack("<H", len(raw))
        names_blob += raw

    streets_blob = bytearray()
    for i, row in enumerate(street_rows):
        streets_blob += struct.pack(
            "<IIiiIH6x",
            row["name_id"] & 0xFFFFFFFF,
            row["norm_id"] & 0xFFFFFFFF,
            to_e7(row["lat"]),
            to_e7(row["lon"]),
            street_houses_off[i] & 0xFFFFFFFF,
            street_houses_count[i] & 0xFFFF,
        )
    assert len(streets_blob) == len(street_rows) * STREET_SZ

    # Layout
    off = HEADER_SIZE
    names_index_off = off
    off += 4 * len(names)
    names_blob_off = off
    off += len(names_blob)
    streets_off = off
    off += len(streets_blob)
    houses_blob_off = off
    off += len(houses_blob)
    admins_off = off
    off += len(admins_blob)
    pois_off = off
    off += len(pois_blob)
    tokens_off = off
    off += len(token_recs)
    postings_off = off
    off += len(postings_blob)
    keys_off = off
    off += len(keys_blob)
    house_global_off = off
    off += len(house_global)
    grid_cell_count = len(grid_items)
    grid_index_off = off
    off += len(grid_index)
    grid_postings_off = off
    off += len(grid_postings)
    norm_index_off = off
    off += len(norm_index)

    house_global_count = len(house_global) // HOUSE_GLOBAL_SZ

    # Header: 4s+BBH (8) + 21*u32 (84) + pad4 = 96
    header = struct.pack(
        "<4sBBH" + "I" * 21 + "4x",
        MAGIC,
        VERSION,
        0,
        0,
        len(names),
        len(street_rows),
        house_global_count,
        len(admins),
        len(token_items),
        names_index_off,
        streets_off,
        houses_blob_off,
        admins_off,
        tokens_off,
        postings_off,
        names_blob_off,
        keys_off,
        house_global_off,
        grid_cell_count,
        grid_index_off,
        grid_postings_off,
        len(norm_index) // NORM_IDX_SZ if NORM_IDX_SZ else 0,
        norm_index_off,
        len(pois),
        pois_off,
    )
    assert len(header) == HEADER_SIZE, "header=%d expected %d" % (len(header), HEADER_SIZE)

    out = bytearray()
    out += header
    for o in name_offsets:
        out += struct.pack("<I", o)
    out += names_blob
    out += streets_blob
    out += houses_blob
    out += admins_blob
    out += pois_blob
    out += token_recs
    out += postings_blob
    out += keys_blob
    out += house_global
    out += grid_index
    out += grid_postings
    out += norm_index
    assert len(out) == off, "size mismatch %d vs %d" % (len(out), off)
    return bytes(out)


def _build_search_bin_legacy(names, streets, addrs, admins, token_map, pois=None):
    """Wrapper for old API — convert to new street tuple shape."""
    new_streets = []
    street_groups = defaultdict(list)
    for name_id, lat, lon, flags in streets:
        street_groups[name_id].append((lat, lon))
    for name_id, pts in street_groups.items():
        lat = sum(p[0] for p in pts) / len(pts)
        lon = sum(p[1] for p in pts) / len(pts)
        new_streets.append((name_id, lat, lon, names[name_id], []))
    return build_search_bin(names, new_streets, addrs, admins, token_map, pois)


if __name__ == "__main__":
    names = ["Quốc lộ 1", "Nguyễn Trãi", "Phường 1"]
    streets = [
        (0, 10.7, 106.6, "Quốc lộ 1", [(12, 10.71, 106.61)]),
        (1, 10.75, 106.65, "Nguyễn Trãi", []),
    ]
    addrs = [(1, "12", 10.75, 106.65, 0)]
    admins = [(2, 10.75, 106.65, 8)]
    data = build_search_bin(names, streets, addrs, admins, None)
    print("Built %d bytes, magic=%s, header=%d" % (len(data), data[:4], HEADER_SIZE))
    # Sanity: street / house sizes
    assert struct.calcsize("<IIiiIH6x") == STREET_SZ
    assert struct.calcsize("<HHii") == HOUSE_ENTRY_SZ
    assert struct.calcsize("<IHHii") == HOUSE_GLOBAL_SZ
    print("OK record sizes")
