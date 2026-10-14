#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""34 tỉnh/TP sau sắp xếp 12/6/2025 (Nghị quyết 202/2025/QH15).

bbox = (minLon, minLat, maxLon, maxLat) — union các tỉnh cũ nếu đã sáp nhập.
aliases gồm tên tỉnh cũ để CLI/UI vẫn khớp.
"""
from __future__ import print_function

# id, name, aliases, minLon, minLat, maxLon, maxLat
# aliases: không dấu / tên tỉnh cũ trước sáp nhập
_PROVINCE_ROWS = (
    # --- Giữ nguyên ---
    ("ha_noi", "Hà Nội", ("ha noi", "hanoi"), 105.45, 20.70, 106.05, 21.40),
    ("cao_bang", "Cao Bằng", ("cao bang",), 105.50, 22.35, 106.85, 23.15),
    ("dien_bien", "Điện Biên", ("dien bien",), 102.15, 20.90, 103.60, 22.55),
    ("lai_chau", "Lai Châu", ("lai chau",), 102.85, 21.70, 103.80, 22.85),
    ("son_la", "Sơn La", ("son la",), 103.20, 20.65, 105.05, 22.05),
    ("lang_son", "Lạng Sơn", ("lang son",), 106.20, 21.50, 107.35, 22.45),
    ("quang_ninh", "Quảng Ninh", ("quang ninh",), 106.45, 20.70, 108.10, 21.70),
    ("thanh_hoa", "Thanh Hóa", ("thanh hoa",), 104.35, 19.30, 106.10, 20.70),
    ("nghe_an", "Nghệ An", ("nghe an",), 103.85, 18.35, 105.85, 19.95),
    ("ha_tinh", "Hà Tĩnh", ("ha tinh",), 105.20, 17.85, 106.60, 18.75),
    ("hue", "Huế", ("hue", "thua thien hue", "thừa thiên huế"), 107.00, 16.00, 108.25, 16.75),
    # --- Sáp nhập (tên mới = union bbox tỉnh cũ) ---
    # Tuyên Quang ← Hà Giang + Tuyên Quang
    ("tuyen_quang", "Tuyên Quang",
     ("tuyen quang", "ha giang"), 104.55, 21.45, 105.60, 23.40),
    # Lào Cai ← Yên Bái + Lào Cai
    ("lao_cai", "Lào Cai",
     ("lao cai", "yen bai"), 103.60, 21.30, 105.15, 22.85),
    # Thái Nguyên ← Bắc Kạn + Thái Nguyên
    ("thai_nguyen", "Thái Nguyên",
     ("thai nguyen", "bac kan", "bac can"), 105.50, 21.30, 106.25, 22.75),
    # Phú Thọ ← Vĩnh Phúc + Hòa Bình + Phú Thọ
    ("phu_tho", "Phú Thọ",
     ("phu tho", "vinh phuc", "hoa binh"), 104.80, 20.30, 105.85, 21.70),
    # Bắc Ninh ← Bắc Giang + Bắc Ninh
    ("bac_ninh", "Bắc Ninh",
     ("bac ninh", "bac giang"), 105.85, 20.95, 107.05, 21.65),
    # Hưng Yên ← Thái Bình + Hưng Yên
    ("hung_yen", "Hưng Yên",
     ("hung yen", "thai binh"), 105.85, 20.20, 106.65, 21.05),
    # Hải Phòng ← Hải Dương + Hải Phòng
    ("hai_phong", "Hải Phòng",
     ("hai phong", "haiphong", "hai duong"), 106.15, 20.55, 107.10, 21.15),
    # Ninh Bình ← Hà Nam + Nam Định + Ninh Bình
    ("ninh_binh", "Ninh Bình",
     ("ninh binh", "ha nam", "nam dinh"), 105.55, 19.95, 106.55, 20.70),
    # Quảng Trị ← Quảng Bình + Quảng Trị
    ("quang_tri", "Quảng Trị",
     ("quang tri", "quang binh"), 105.60, 16.40, 107.55, 18.10),
    # Đà Nẵng ← Quảng Nam + Đà Nẵng
    ("da_nang", "Đà Nẵng",
     ("da nang", "danang", "quang nam"), 107.35, 14.95, 108.80, 16.25),
    # Quảng Ngãi ← Kon Tum + Quảng Ngãi
    ("quang_ngai", "Quảng Ngãi",
     ("quang ngai", "kon tum"), 107.35, 14.00, 109.15, 15.45),
    # Gia Lai ← Bình Định + Gia Lai
    ("gia_lai", "Gia Lai",
     ("gia lai", "binh dinh", "pleiku"), 107.40, 13.20, 109.35, 14.70),
    # Khánh Hòa ← Ninh Thuận + Khánh Hòa
    ("khanh_hoa", "Khánh Hòa",
     ("khanh hoa", "ninh thuan", "nha trang"), 108.55, 11.30, 109.45, 12.90),
    # Lâm Đồng ← Đắk Nông + Bình Thuận + Lâm Đồng
    ("lam_dong", "Lâm Đồng",
     ("lam dong", "dak nong", "binh thuan", "da lat", "dalat", "phan thiet"),
     107.20, 10.55, 108.85, 12.65),
    # Đắk Lắk ← Phú Yên + Đắk Lắk
    ("dak_lak", "Đắk Lắk",
     ("dak lak", "daklak", "phu yen", "buon ma thuot"), 107.50, 12.15, 109.45, 13.70),
    # TP.HCM ← BR-VT + Bình Dương + HCM
    ("ho_chi_minh", "Hồ Chí Minh",
     ("ho chi minh", "tp hcm", "saigon", "sai gon", "hcm",
      "ba ria vung tau", "vung tau", "ba ria", "binh duong"),
     106.35, 10.25, 107.60, 11.55),
    # Đồng Nai ← Bình Phước + Đồng Nai
    ("dong_nai", "Đồng Nai",
     ("dong nai", "binh phuoc"), 106.40, 10.55, 107.55, 12.30),
    # Tây Ninh ← Long An + Tây Ninh
    ("tay_ninh", "Tây Ninh",
     ("tay ninh", "long an"), 105.50, 10.25, 106.85, 11.80),
    # Cần Thơ ← Sóc Trăng + Hậu Giang + Cần Thơ
    ("can_tho", "Cần Thơ",
     ("can tho", "soc trang", "hau giang"), 105.35, 9.25, 106.25, 10.35),
    # Vĩnh Long ← Bến Tre + Trà Vinh + Vĩnh Long
    ("vinh_long", "Vĩnh Long",
     ("vinh long", "ben tre", "tra vinh"), 105.70, 9.55, 106.80, 10.35),
    # Đồng Tháp ← Tiền Giang + Đồng Tháp
    ("dong_thap", "Đồng Tháp",
     ("dong thap", "tien giang"), 105.20, 10.15, 106.75, 10.95),
    # Cà Mau ← Bạc Liêu + Cà Mau
    ("ca_mau", "Cà Mau",
     ("ca mau", "bac lieu"), 104.70, 8.35, 105.95, 9.55),
    # An Giang ← Kiên Giang + An Giang
    ("an_giang", "An Giang",
     ("an giang", "kien giang", "phu quoc"), 104.40, 9.35, 105.55, 10.95),
)

# Biển Đông — Hoàng Sa / Trường Sa (cần PBF riêng từ BBBike)
BIEN_DONG = ("bien_dong", "Biển Đông (Hoàng Sa – Trường Sa)",
             ("bien dong", "hoang sa", "truong sa"), 110.5, 7.0, 117.5, 17.8)


def _norm(s):
    s = (s or "").strip().lower()
    repl = (
        ("àáạảãâầấậẩẫăằắặẳẵ", "a"),
        ("èéẹẻẽêềếệểễ", "e"),
        ("ìíịỉĩ", "i"),
        ("òóọỏõôồốộổỗơờớợởỡ", "o"),
        ("ùúụủũưừứựửữ", "u"),
        ("ỳýỵỷỹ", "y"),
        ("đ", "d"),
    )
    for chars, to in repl:
        for c in chars:
            s = s.replace(c, to)
    s = s.replace("-", " ").replace("_", " ")
    while "  " in s:
        s = s.replace("  ", " ")
    return s


def all_provinces():
    out = []
    for row in _PROVINCE_ROWS:
        pid, name, aliases = row[0], row[1], row[2]
        bbox = row[3:7]
        out.append({
            "id": pid,
            "name": name,
            "aliases": tuple(aliases),
            "bbox": bbox,
        })
    pid, name, aliases = BIEN_DONG[0], BIEN_DONG[1], BIEN_DONG[2]
    out.append({
        "id": pid,
        "name": name,
        "aliases": tuple(aliases),
        "bbox": BIEN_DONG[3:7],
        "needs_bien_dong_pbf": True,
    })
    return out


def resolve_province(token):
    key = _norm(token)
    if not key:
        return None
    for p in all_provinces():
        if key == _norm(p["id"]) or key == _norm(p["name"]):
            return p
        for a in p["aliases"]:
            if key == _norm(a):
                return p
    for p in all_provinces():
        if _norm(p["name"]).startswith(key) or key.startswith(_norm(p["name"])):
            return p
    return None


def resolve_provinces(text_or_list):
    if text_or_list is None:
        return [], []
    if isinstance(text_or_list, (list, tuple)):
        tokens = list(text_or_list)
    else:
        raw = str(text_or_list).replace(";", ",").replace("|", ",")
        tokens = [t.strip() for t in raw.split(",") if t.strip()]
    found = []
    unknown = []
    seen = set()
    for t in tokens:
        p = resolve_province(t)
        if p is None:
            unknown.append(t)
            continue
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        found.append(p)
    return found, unknown


def merge_bbox(provinces, pad=0.05):
    if not provinces:
        return None
    min_lon = min(p["bbox"][0] for p in provinces)
    min_lat = min(p["bbox"][1] for p in provinces)
    max_lon = max(p["bbox"][2] for p in provinces)
    max_lat = max(p["bbox"][3] for p in provinces)
    return (min_lon - pad, min_lat - pad, max_lon + pad, max_lat + pad)


def format_bbox(bbox):
    return "%.4f,%.4f,%.4f,%.4f" % bbox


def needs_bien_dong_pbf(provinces):
    return any(p.get("needs_bien_dong_pbf") or p["id"] == "bien_dong" for p in provinces)


def build_old_to_new_province_map():
    """Build mapping from old province names (OSM tags) to new merged province names."""
    mapping = {}
    for row in _PROVINCE_ROWS:
        new_name = row[1]
        aliases = row[2]
        for alias in aliases:
            mapping[_norm(alias)] = new_name
        mapping[_norm(new_name)] = new_name
    return mapping


OLD_TO_NEW_PROVINCE = build_old_to_new_province_map()


def map_old_province_to_new(province_name):
    """Map old province name (from OSM tags) to new merged province name."""
    if not province_name:
        return None
    # Strip common Vietnamese prefixes
    name = province_name.strip()
    for prefix in ("Tỉnh ", "Tỉnh ", "Thành phố ", "Thành Phố ", "Thành phố ", "Thành Phố "):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    key = _norm(name)
    return OLD_TO_NEW_PROVINCE.get(key, province_name)
