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

# Vùng chứa từng tỉnh (id vùng trong vn_regions.REGIONS) — chỉ để mô tả/hiển thị; dữ liệu thật xuất theo bbox.
# Phân vùng theo 6 vùng kinh tế - xã hội, áp cho 34 đơn vị sau sáp nhập (tỉnh nhiều vùng cũ lấy vùng của tỉnh trung tâm).
PROVINCE_REGION = {
    # Trung du và miền núi phía Bắc (9)
    "tuyen_quang": "mien_nui_phia_bac", "lao_cai": "mien_nui_phia_bac", "thai_nguyen": "mien_nui_phia_bac",
    "phu_tho": "mien_nui_phia_bac", "cao_bang": "mien_nui_phia_bac", "lang_son": "mien_nui_phia_bac",
    "lai_chau": "mien_nui_phia_bac", "dien_bien": "mien_nui_phia_bac", "son_la": "mien_nui_phia_bac",
    # Đồng bằng sông Hồng (6)
    "ha_noi": "dong_bang_song_hong", "hai_phong": "dong_bang_song_hong", "quang_ninh": "dong_bang_song_hong",
    "bac_ninh": "dong_bang_song_hong", "hung_yen": "dong_bang_song_hong", "ninh_binh": "dong_bang_song_hong",
    # Bắc Trung Bộ (5)
    "thanh_hoa": "bac_trung_bo", "nghe_an": "bac_trung_bo", "ha_tinh": "bac_trung_bo",
    "quang_tri": "bac_trung_bo", "hue": "bac_trung_bo",
    # Duyên hải Nam Trung Bộ và Tây Nguyên (6)
    "da_nang": "nam_trung_bo_tay_nguyen", "quang_ngai": "nam_trung_bo_tay_nguyen",
    "gia_lai": "nam_trung_bo_tay_nguyen", "dak_lak": "nam_trung_bo_tay_nguyen",
    "khanh_hoa": "nam_trung_bo_tay_nguyen", "lam_dong": "nam_trung_bo_tay_nguyen",
    # Đông Nam Bộ (3)
    "ho_chi_minh": "dong_nam_bo", "dong_nai": "dong_nam_bo", "tay_ninh": "dong_nam_bo",
    # Đồng bằng sông Cửu Long (5)
    "can_tho": "dong_bang_song_cuu_long", "vinh_long": "dong_bang_song_cuu_long",
    "dong_thap": "dong_bang_song_cuu_long", "ca_mau": "dong_bang_song_cuu_long",
    "an_giang": "dong_bang_song_cuu_long",
}

# Mốc xác định tỉnh theo vị trí: thủ phủ các tỉnh CŨ (trước sáp nhập) → id tỉnh/thành MỚI chứa nó.
# App dùng "mốc gần nhất" để đoán tỉnh của người dùng (khung bbox quá thô ở vùng giáp ranh, vd. Đà Nẵng/Huế).
# (vĩ độ, kinh độ, id tỉnh mới) — sai số ~0.1° là đủ, chỉ để gọi tên tỉnh/chọn vùng.
PROVINCE_ANCHORS = (
    (21.03, 105.85, "ha_noi"),
    (22.67, 106.25, "cao_bang"),
    (21.39, 103.02, "dien_bien"),
    (22.40, 103.46, "lai_chau"),
    (21.33, 103.91, "son_la"),
    (21.85, 106.76, "lang_son"),
    (20.95, 107.08, "quang_ninh"),
    (19.81, 105.78, "thanh_hoa"),
    (18.68, 105.68, "nghe_an"),
    (18.34, 105.91, "ha_tinh"),
    (16.46, 107.59, "hue"),
    (21.82, 105.21, "tuyen_quang"),
    (22.82, 104.98, "tuyen_quang"),    # Hà Giang cũ
    (22.48, 103.97, "lao_cai"),
    (21.72, 104.90, "lao_cai"),        # Yên Bái cũ
    (21.59, 105.84, "thai_nguyen"),
    (22.15, 105.83, "thai_nguyen"),    # Bắc Kạn cũ
    (21.32, 105.40, "phu_tho"),
    (21.31, 105.60, "phu_tho"),        # Vĩnh Phúc cũ
    (20.82, 105.34, "phu_tho"),        # Hòa Bình cũ
    (21.19, 106.07, "bac_ninh"),
    (21.27, 106.19, "bac_ninh"),       # Bắc Giang cũ
    (20.65, 106.05, "hung_yen"),
    (20.45, 106.34, "hung_yen"),       # Thái Bình cũ
    (20.86, 106.68, "hai_phong"),
    (20.94, 106.33, "hai_phong"),      # Hải Dương cũ
    (20.25, 105.97, "ninh_binh"),
    (20.54, 105.91, "ninh_binh"),      # Hà Nam cũ
    (20.43, 106.18, "ninh_binh"),      # Nam Định cũ
    (16.82, 107.10, "quang_tri"),
    (17.47, 106.62, "quang_tri"),      # Quảng Bình cũ
    (16.05, 108.20, "da_nang"),
    (15.57, 108.48, "da_nang"),        # Quảng Nam cũ
    (15.12, 108.80, "quang_ngai"),
    (14.35, 108.00, "quang_ngai"),     # Kon Tum cũ
    (13.98, 108.00, "gia_lai"),
    (13.78, 109.22, "gia_lai"),        # Bình Định cũ
    (12.24, 109.19, "khanh_hoa"),
    (11.56, 108.99, "khanh_hoa"),      # Ninh Thuận cũ
    (11.94, 108.44, "lam_dong"),
    (12.00, 107.69, "lam_dong"),       # Đắk Nông cũ
    (10.93, 108.10, "lam_dong"),       # Bình Thuận cũ
    (12.67, 108.04, "dak_lak"),
    (13.09, 109.31, "dak_lak"),        # Phú Yên cũ
    (10.78, 106.70, "ho_chi_minh"),
    (10.35, 107.08, "ho_chi_minh"),    # Bà Rịa - Vũng Tàu cũ
    (10.99, 106.65, "ho_chi_minh"),    # Bình Dương cũ
    (10.95, 106.82, "dong_nai"),
    (11.53, 106.89, "dong_nai"),       # Bình Phước cũ
    (11.31, 106.10, "tay_ninh"),
    (10.54, 106.41, "tay_ninh"),       # Long An cũ
    (10.04, 105.78, "can_tho"),
    (9.60, 105.97, "can_tho"),         # Sóc Trăng cũ
    (9.78, 105.47, "can_tho"),         # Hậu Giang cũ
    (10.25, 105.97, "vinh_long"),
    (10.24, 106.38, "vinh_long"),      # Bến Tre cũ
    (9.93, 106.34, "vinh_long"),       # Trà Vinh cũ
    (10.46, 105.63, "dong_thap"),
    (10.36, 106.36, "dong_thap"),      # Tiền Giang cũ
    (9.18, 105.15, "ca_mau"),
    (9.29, 105.72, "ca_mau"),          # Bạc Liêu cũ
    (10.38, 105.43, "an_giang"),
    (10.01, 105.08, "an_giang"),       # Kiên Giang cũ
    (10.23, 103.97, "an_giang"),       # Phú Quốc
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
            "region": PROVINCE_REGION.get(pid),
        })
    pid, name, aliases = BIEN_DONG[0], BIEN_DONG[1], BIEN_DONG[2]
    out.append({
        "id": pid,
        "name": name,
        "aliases": tuple(aliases),
        "bbox": BIEN_DONG[3:7],
        "region": "bien_dong",
        "needs_bien_dong_pbf": True,
    })
    return out


def mainland_provinces():
    """34 tỉnh/thành sau sáp nhập (không gồm bien_dong) — mỗi đơn vị một thư mục snake_case khi xuất --mode provinces."""
    return [p for p in all_provinces() if p["id"] != BIEN_DONG[0]]


def provinces_of_region(region_id):
    """Tên các tỉnh/thành thuộc một vùng (để hiển thị)."""
    return [p["name"] for p in mainland_provinces() if p["region"] == region_id]


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
