#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Định nghĩa vùng map/routing — khớp SpeedAlertPaths.ROUTING_REGIONS (Java)."""
from __future__ import print_function

# id, label, minLon, minLat, maxLon, maxLat
REGIONS = (
    ("mien_nui_phia_bac", "Trung du và miền núi phía Bắc", 102.0, 20.4, 108.5, 23.5),
    ("dong_bang_song_hong", "Đồng bằng sông Hồng", 105.0, 19.7, 108.2, 21.7),
    ("bac_trung_bo", "Bắc Trung Bộ", 103.5, 16.0, 108.5, 20.5),
    ("nam_trung_bo_tay_nguyen", "Duyên hải Nam Trung Bộ và Tây Nguyên", 104.5, 10.8, 109.8, 16.5),
    ("dong_nam_bo", "Đông Nam Bộ", 105.0, 10.2, 108.0, 12.5),
    ("dong_bang_song_cuu_long", "Đồng bằng sông Cửu Long", 103.5, 8.2, 107.2, 11.2),
    ("bien_dong", "Biển Đông (Hoàng Sa – Trường Sa)", 110.5, 7.0, 117.5, 17.8),
)

VIET_NAM_ID = "viet_nam"
VIET_NAM_LABEL = "Viet Nam (toan quoc)"

DEFAULT_VIETNAM_PBF = "vietnam.osm.pbf"
DEFAULT_BIEN_DONG_PBF = "hoangsa_truongsa.pbf"
