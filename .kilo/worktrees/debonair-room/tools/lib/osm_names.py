#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Chọn tên hiển thị từ tag OSM — ưu tiên tiếng Việt, bỏ chữ Trung nếu không có VI."""
from __future__ import print_function

# name:* ngôn ngữ Trung — không dùng làm nhãn
ZH_KEYS = frozenset((
    "name:zh", "name:zh-Hans", "name:zh-Hant", "name:zh-CN", "name:zh-TW",
    "name:zh_pinyin", "name:zh-Latn-pinyin",
))

ROAD_PREFIXES = (
    "Đường ", "đường ", "Duong ", "duong ",
    "Phố ", "phố ", "Pho ", "pho ",
)


def has_cjk(text):
    """True nếu chuỗi chứa chữ Hán / CJK (kể cả fullwidth)."""
    if not text:
        return False
    for ch in text:
        o = ord(ch)
        if (0x4E00 <= o <= 0x9FFF or
                0x3400 <= o <= 0x4DBF or
                0xF900 <= o <= 0xFAFF or
                0x3000 <= o <= 0x303F or
                0xFF00 <= o <= 0xFFEF):
            return True
    return False


def _strip_road_prefix(name):
    for prefix in ROAD_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
            break
    return name


def pick_name(tags, keys=("name:vi", "name", "name:en", "official_name"),
              strip_road_prefix=False):
    """Ưu tiên name:vi; bỏ tag/zh và mọi chuỗi CJK khi không có bản VI.

    Không có tên VI tương ứng → trả None (xóa sạch text Trung), geometry vẫn giữ.
    """
    if not tags:
        return None

    vi = (tags.get("name:vi") or "").strip()
    if vi:
        return _strip_road_prefix(vi) if strip_road_prefix else vi

    for k in keys:
        if k == "name:vi" or k in ZH_KEYS:
            continue
        if k.startswith("name:zh"):
            continue
        v = tags.get(k)
        if not v:
            continue
        name = v.strip()
        if not name or has_cjk(name):
            continue
        if strip_road_prefix:
            name = _strip_road_prefix(name)
        return name if name else None
    return None


def road_name(tags):
    # Ưu tiên name:vi, name, name:en, official_name
    name = pick_name(
        tags,
        keys=("name:vi", "name", "name:en", "official_name"),
        strip_road_prefix=True,
    )
    if name:
        return name
    # Fallback: format ref based on highway type
    hw = tags.get("highway")
    ref = tags.get("ref")
    if ref:
        ref = ref.strip()
        if hw in ("motorway", "motorway_link", "trunk", "trunk_link"):
            # QL (Quốc lộ)
            return "QL" + ref if not ref.upper().startswith("QL") else ref.upper()
        elif hw in ("primary", "primary_link"):
            # QL or ĐT (Đường tỉnh)
            return "QL" + ref if not ref.upper().startswith(("QL", "ĐT", "DT")) else ref.upper()
        elif hw in ("secondary", "secondary_link"):
            # ĐT (Đường tỉnh) or TL (Tỉnh lộ)
            return "ĐT" + ref if not ref.upper().startswith(("QL", "ĐT", "DT", "TL")) else ref.upper()
        elif hw in ("tertiary", "tertiary_link"):
            # TL (Tỉnh lộ) or ĐT
            return "TL" + ref if not ref.upper().startswith(("QL", "ĐT", "DT", "TL")) else ref.upper()
        else:
            # unclassified, residential, etc. - skip bare numeric refs
            if ref.isdigit():
                return None
            return ref
    return None


def place_name(tags):
    return pick_name(
        tags,
        keys=("name:vi", "name", "name:en", "official_name"),
        strip_road_prefix=False,
    )
