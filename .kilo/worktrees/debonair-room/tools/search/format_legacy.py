#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Format search.bin (GNavi offline geocoder) + normalize tiếng Việt.

Layout little-endian, version 1 — random-access, không cần load cả file vào RAM.

HEADER 64 bytes
  0  magic           b'GNS1'
  4  version         u8 (=1)
  5  reserved        u8
  6  flags           u16
  8  name_count      u32
 12  street_count    u32
 16  addr_count      u32
 20  admin_count     u32
 24  token_count     u32
 28  names_offset    u32   # u32[name_count] offsets into name blob, then blob
 32  streets_offset  u32   # StreetRec[street_count] fixed 16B
 36  addrs_offset    u32   # AddrRec[addr_count] fixed 20B
 40  admins_offset   u32   # AdminRec[admin_count] fixed 16B
 44  tokens_offset   u32   # TokenRec[token_count] fixed 16B, sorted by key
 48  postings_offset u32
 52  names_blob_off  u32
 56  keys_blob_off   u32
 60  reserved2       u32

StreetRec 16B: name_id u32, lat_e7 i32, lon_e7 i32, flags u32
AddrRec   20B: name_id u32, house_id u32, lat_e7 i32, lon_e7 i32, flags u32
AdminRec  16B: name_id u32, lat_e7 i32, lon_e7 i32, level u8, pad[3]
TokenRec  16B: key_off u32, key_len u16, pad u16, post_off u32, post_count u32

Posting id packing:
  bits 31..30 = type (1=street, 2=addr, 3=admin)
  bits 29..0  = record index
"""
from __future__ import print_function

import re
import struct
import unicodedata

MAGIC = b"GNS1"
VERSION = 1
HEADER_SIZE = 64
STREET_SIZE = 16
ADDR_SIZE = 20
ADMIN_SIZE = 16
TOKEN_SIZE = 16

TYPE_STREET = 1
TYPE_ADDR = 2
TYPE_ADMIN = 3
TYPE_POI = 4

# place= → admin level bucket
PLACE_LEVEL = {
    "city": 4,
    "town": 5,
    "municipality": 5,
    "suburb": 6,
    "borough": 6,
    "district": 6,
    "village": 7,
    "hamlet": 8,
    "neighbourhood": 8,
    "quarter": 8,
    "city_block": 9,
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
    parts = norm.split()
    out = []
    for p in parts:
        if len(p) == 0:
            continue
        out.append(p)
    return out


_HOUSE_RE = re.compile(
    r"^(\d{1,5}[a-z]?(?:[/-]\d{1,5}[a-z]?)?)$", re.I
)


def is_house_token(tok):
    return bool(_HOUSE_RE.match(tok or ""))


def parse_query(raw):
    """→ (house_or_None, text_tokens[], display_norm)."""
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


def build_search_bin(names, streets, addrs, admins, token_map):
    """
    names: list[str] display names (index = name_id)
    streets: list[(name_id, lat, lon, flags)]
    addrs: list[(name_id, house_str, lat, lon, flags)]
    admins: list[(name_id, lat, lon, level)]
    token_map: dict[str, list[packed_id]]  (will be sorted)
    """
    # house strings share name pool
    house_ids = {}
    for i, a in enumerate(addrs):
        h = a[1]
        if h not in house_ids:
            house_ids[h] = len(names)
            names.append(h)

    # name offsets + blob
    name_offsets = []
    names_blob = bytearray()
    for nm in names:
        raw = (nm or "").encode("utf-8")
        if len(raw) > 65535:
            raw = raw[:65535]
        name_offsets.append(len(names_blob))
        names_blob += struct.pack("<H", len(raw))
        names_blob += raw

    # streets / addrs / admins blobs
    streets_blob = bytearray()
    for name_id, lat, lon, flags in streets:
        streets_blob += struct.pack(
            "<IiiI", name_id, to_e7(lat), to_e7(lon), flags & 0xFFFFFFFF
        )

    addrs_blob = bytearray()
    for name_id, house, lat, lon, flags in addrs:
        hid = house_ids[house]
        addrs_blob += struct.pack(
            "<IIiiI", name_id, hid, to_e7(lat), to_e7(lon), flags & 0xFFFFFFFF
        )

    admins_blob = bytearray()
    for name_id, lat, lon, level in admins:
        admins_blob += struct.pack(
            "<IiiB3x", name_id, to_e7(lat), to_e7(lon), level & 0xFF
        )

    # tokens sorted + postings
    token_items = sorted(token_map.items(), key=lambda kv: kv[0])
    keys_blob = bytearray()
    postings_blob = bytearray()
    token_recs = bytearray()
    for key, ids in token_items:
        # dedupe + sort postings
        uniq = sorted(set(ids))
        key_raw = key.encode("utf-8")
        if len(key_raw) > 65535:
            key_raw = key_raw[:65535]
        key_off = len(keys_blob)
        keys_blob += key_raw
        post_off = len(postings_blob)
        for pid in uniq:
            postings_blob += struct.pack("<I", pid & 0xFFFFFFFF)
        token_recs += struct.pack(
            "<IHHII",
            key_off,
            len(key_raw),
            0,
            post_off,
            len(uniq),
        )

    # layout offsets
    off = HEADER_SIZE
    names_index_off = off
    off += 4 * len(names)
    names_blob_off = off
    off += len(names_blob)
    streets_off = off
    off += len(streets_blob)
    addrs_off = off
    off += len(addrs_blob)
    admins_off = off
    off += len(admins_blob)
    tokens_off = off
    off += len(token_recs)
    postings_off = off
    off += len(postings_blob)
    keys_off = off
    # keys at end

    # 4s+BBH (8) + 14*u32 (56) = 64
    header = struct.pack(
        "<4sBBH" + "I" * 14,
        MAGIC,
        VERSION,
        0,
        0,
        len(names),
        len(streets),
        len(addrs),
        len(admins),
        len(token_items),
        names_index_off,   # 28
        streets_off,       # 32
        addrs_off,         # 36
        admins_off,        # 40
        tokens_off,        # 44
        postings_off,      # 48
        names_blob_off,    # 52
        keys_off,          # 56
        0,                 # 60 reserved
    )
    assert len(header) == HEADER_SIZE, len(header)

    out = bytearray()
    out += header
    for o in name_offsets:
        out += struct.pack("<I", o)
    out += names_blob
    out += streets_blob
    out += addrs_blob
    out += admins_blob
    out += token_recs
    out += postings_blob
    out += keys_blob
    assert len(out) == keys_off + len(keys_blob)
    return bytes(out)


def build_search_bin(names, streets, addrs, admins, pois, token_map):
    """
    Extended format with POI support (GNS3).
    POI record: name_id u32, lat_e7 i32, lon_e7 i32, category u8, pad[3]
    If token_map is None, builds unigram + bigram index from names.
    """
    # house strings share name pool
    house_ids = {}
    for i, a in enumerate(addrs):
        h = a[1]
        if h not in house_ids:
            house_ids[h] = len(names)
            names.append(h)

    # name offsets + blob
    name_offsets = []
    names_blob = bytearray()
    for nm in names:
        raw = (nm or "").encode("utf-8")
        if len(raw) > 65535:
            raw = raw[:65535]
        name_offsets.append(len(names_blob))
        names_blob += struct.pack("<H", len(raw))
        names_blob += raw

    # streets / addrs / admins / pois blobs
    streets_blob = bytearray()
    for name_id, lat, lon, flags in streets:
        streets_blob += struct.pack("<IiiI", name_id, to_e7(lat), to_e7(lon), flags & 0xFFFFFFFF)

    addrs_blob = bytearray()
    for name_id, house, lat, lon, flags in addrs:
        hid = house_ids[house]
        addrs_blob += struct.pack("<IIiiI", name_id, hid, to_e7(lat), to_e7(lon), flags & 0xFFFFFFFF)

    admins_blob = bytearray()
    for name_id, lat, lon, level in admins:
        admins_blob += struct.pack("<IiiB3x", name_id, to_e7(lat), to_e7(lon), level & 0xFF)

    pois_blob = bytearray()
    for name_id, lat, lon, category in pois:
        pois_blob += struct.pack("<IiiB3x", name_id, to_e7(lat), to_e7(lon), category & 0xFF)

    # build token map if not provided
    if token_map is None:
        token_map = {}
        for name_id, display in enumerate(names):
            norm = normalize_vi(display)
            toks = tokenize(norm)
            for i, tok in enumerate(toks):
                token_map.setdefault(tok, []).append(pack_id(TYPE_STREET, name_id))
            # bigrams
            for i in range(len(toks) - 1):
                bigram = toks[i] + " " + toks[i + 1]
                token_map.setdefault(bigram, []).append(pack_id(TYPE_STREET, name_id))

    # tokens sorted + postings
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
        token_recs += struct.pack("<IHHII", key_off, len(key_raw), 0, post_off, len(uniq))

    # layout offsets
    HEADER_SIZE_V3 = 72  # +8 for pois_offset
    off = HEADER_SIZE_V3
    names_index_off = off
    off += 4 * len(names)
    names_blob_off = off
    off += len(names_blob)
    streets_off = off
    off += len(streets_blob)
    addrs_off = off
    off += len(addrs_blob)
    admins_off = off
    off += len(admins_blob)
    pois_off = off
    off += len(pois_blob)
    tokens_off = off
    off += len(token_recs)
    postings_off = off
    off += len(postings_blob)
    keys_off = off

    # 4s+BBH (8) + 16*u32 (64) = 72
    header = struct.pack(
        "<4sBBH" + "I" * 16,
        MAGIC,
        3,  # version 3
        0,
        0,
        len(names),
        len(streets),
        len(addrs),
        len(admins),
        len(pois),
        len(token_items),
        names_index_off,
        streets_off,
        addrs_off,
        admins_off,
        pois_off,
        tokens_off,
        postings_off,
        names_blob_off,
        keys_off,
        0,
    )
    assert len(header) == HEADER_SIZE_V3, len(header)

    out = bytearray()
    out += header
    for o in name_offsets:
        out += struct.pack("<I", o)
    out += names_blob
    out += streets_blob
    out += addrs_blob
    out += admins_blob
    out += pois_blob
    out += token_recs
    out += postings_blob
    out += keys_blob
    assert len(out) == keys_off + len(keys_blob)
    return bytes(out)
