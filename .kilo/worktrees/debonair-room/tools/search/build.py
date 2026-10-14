#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OSM PBF -> search.bin GNS3 (offline geocoder) -- single command.

Usage:
  python search.py vietnam.osm.pbf out/alert_data/search.bin --also hoangsa_truongsa.pbf
  python search.py vietnam.osm.pbf out/alert_data/search.bin --provinces "Ha Tinh,Da Nang,Quang Nam"
"""
from __future__ import print_function

import argparse
import os
import sys
import time

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from lib.common import add_common_args, ensure_osmium, resolve_bbox_and_pbfs
from lib.osm_names import place_name, road_name
from search.format_gns3 import (
    PLACE_LEVEL,
    TYPE_ADDR,
    TYPE_ADMIN,
    TYPE_POI,
    TYPE_STREET,
    build_search_bin,
    normalize_vi,
    pack_id,
    tokenize,
)

ensure_osmium()
import osmium  # noqa: E402

# Gộp đoạn đường cùng tên trong ô ~2.2 km
BUCKET = 2000  # 0.02° * 1e5 ≈ dùng lat*50
HIGHWAY = frozenset({
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "living_street", "service",
    "road", "track", "motorway_link", "trunk_link", "primary_link",
    "secondary_link", "tertiary_link",
})

# POI categories (extended to cover all common OSM tags)
POI_CATEGORIES = {
    # Education
    "school": 1, "university": 2, "kindergarten": 3, "college": 3, "library": 3,
    "language_school": 3, "music_school": 3, "driving_school": 3,
    "research_institute": 3,
    # Healthcare
    "hospital": 4, "clinic": 5, "pharmacy": 6, "doctors": 6, "dentist": 6,
    "nursing_home": 6, "health_centre": 6, "veterinary": 6,
    # Shopping
    "marketplace": 7, "supermarket": 8, "shop": 9, "convenience": 9, "mall": 9,
    "department_store": 9, "wholesale": 9, "kiosk": 9, "boutique": 9,
    "general": 9, "variety_store": 9, "furniture": 9, "household": 9,
    "hardware": 9, "doityourself": 9, "garden_centre": 9, "nursery": 9,
    "florist": 9, "gift": 9, "gifts": 9, "jewelry": 9, "jewellery": 9,
    "sports": 9, "outdoor": 9, "toys": 9, "books": 9, "stationery": 9,
    "newsagent": 9, "tobacco": 9, "alcohol": 9, "beverages": 9,
    "bakery": 9, "confectionery": 9, "butcher": 9, "seafood": 9,
    "cheese": 9, "greengrocer": 9, "healthfood": 9, "organic": 9,
    "farm": 9, "coffee": 9, "tea": 9, "frozen_food": 9, "ice_cream": 9,
    "deli": 9, "charity": 9, "second_hand": 9, "antiques": 9,
    "art": 9, "camera": 9, "computer": 9, "electronics": 9,
    "mobile_phone": 9, "telecommunication": 9, "video": 9, "video_games": 9,
    "games": 9, "music": 9, "musical_instrument": 9, "optician": 9,
    "medical_supply": 9, "beauty": 9, "cosmetics": 9, "perfumery": 9,
    "hairdresser": 9, "beauty_shop": 9, "tanning": 9, "massage": 9,
    "tattoo": 9, "laundry": 9, "dry_cleaning": 9, "shoe_repair": 9,
    "key_cutter": 9, "locksmith": 9, "copyshop": 9, "photo_studio": 9,
    "computer_repair": 9, "mobile_phone_repair": 9, "electronics_repair": 9,
    "car": 9, "car_repair": 9, "car_parts": 9, "motorcycle": 9,
    "motorcycle_repair": 9, "bicycle": 9, "bicycle_repair": 9,
    "fuel": 9, "charging_station": 9, "car_wash": 9,
    # Food & Drink
    "restaurant": 10, "cafe": 11, "hotel": 12, "bar": 12, "pub": 12,
    "fast_food": 12, "hostel": 12, "motel": 12, "guest_house": 12,
    "nightclub": 12, "karaoke": 12, "casino": 12, "brothel": 12,
    "stripclub": 12, "swingerclub": 12,
    # Banking
    "atm": 13, "bank": 13, "bureau_de_change": 13, "money_transfer": 13,
    # Transport
    "bus_station": 15, "train_station": 15, "ferry_terminal": 15,
    "aerodrome": 16, "airport": 16, "bus_stop": 17, "taxi": 17,
    "car_sharing": 17, "bicycle_rental": 17, "car_rental": 17,
    "motorcycle_rental": 17, "boat_rental": 17,
    # Sports & Recreation
    "park": 18, "pitch": 19, "sports_centre": 19, "stadium": 19,
    "garden": 18, "playground": 19, "swimming_pool": 19, "fitness_centre": 19,
    "golf_course": 19, "tennis": 19, "basketball": 19, "soccer": 19,
    "ski": 19, "ice_skating": 19, "skateboard": 19, "climbing": 19,
    "hiking": 19, "cycling": 19, "horse_riding": 19, "sailing": 19,
    "scuba_diving": 19, "surfing": 19, "fishing": 19, "hunting": 19,
    # Government
    "government": 20, "townhall": 20, "courthouse": 20, "public_building": 20,
    "community_centre": 20, "social_facility": 20, "post_office": 20,
    "police": 20, "fire_station": 20, "embassy": 20, "consulate": 20,
    "office": 20, "company": 20, "lawyer": 20, "insurance": 20,
    "accountant": 20, "estate_agent": 20, "employment_agency": 20,
    "travel_agent": 20,
    # Religion
    "place_of_worship": 21, "church": 21, "mosque": 21, "temple": 21,
    "pagoda": 21, "synagogue": 21, "shrine": 21, "chapel": 21,
    "monastery": 21, "convent": 21,
    # Tourism
    "attraction": 22, "museum": 22, "viewpoint": 22, "zoo": 22,
    "theme_park": 22, "information": 22, "picnic_site": 22,
    "aquarium": 22, "gallery": 22, "artwork": 22, "memorial": 22,
    "monument": 22, "statue": 22, "ruins": 22, "castle": 22,
    "fort": 22, "tower": 22, "windmill": 22, "lighthouse": 22,
    "castle_ruins": 22, "fortress": 22, "historic": 22,
    # Services
    "post_office": 23, "police": 24, "fire_station": 25,
    "industrial": 26, "factory": 26, "warehouse": 26,
    "toilets": 29, "drinking_water": 29, "shower": 29,
    "parking": 30, "parking_entrance": 30, "bicycle_parking": 30,
    "recycling": 32, "waste_basket": 32, "waste_disposal": 32,
    "vending_machine": 33, "telephone": 33,
    "internet_cafe": 38, "spa": 41, "wellness_centre": 41,
    "pet": 63, "pet_grooming": 63,
    # Common building types
    "apartments": 83, "house": 83, "detached": 83, "semidetached_house": 83,
    "terrace": 83, "bungalow": 83, "dormitory": 83, "hotel": 83,
    "motel": 83, "hostel": 83, "commercial": 83, "retail": 83,
    "office": 83, "industrial": 83, "warehouse": 83, "civic": 83,
    "public": 83, "religious": 83, "church": 83, "chapel": 83,
    "mosque": 83, "temple": 83, "pagoda": 83, "synagogue": 83,
    "shrine": 83, "school": 83, "university": 83, "college": 83,
    "hospital": 83, "clinic": 83, "pharmacy": 83, "kindergarten": 83,
    "library": 83, "museum": 83, "theatre": 83, "cinema": 83,
    "gallery": 83, "government": 83, "townhall": 83, "courthouse": 83,
    "police": 83, "fire_station": 83, "post_office": 83,
    "train_station": 83, "bus_station": 83, "airport": 83,
    "stadium": 83, "sports_centre": 83, "swimming_pool": 83,
    "restaurant": 83, "cafe": 83, "bar": 83, "pub": 83,
    "fast_food": 83, "shop": 83, "supermarket": 83, "mall": 83,
    "bank": 83, "atm": 83, "fuel": 83, "parking": 83,
    "yes": 83,  # generic building=yes tag
}


class SearchHandler(osmium.SimpleHandler):
    def __init__(self, bbox=None):
        super(SearchHandler, self).__init__()
        self.bbox = bbox  # minLon,minLat,maxLon,maxLat
        self.names = []
        self.name_to_id = {}
        self.street_merge = {}
        self.addrs = []       # (name_id, house, lat, lon, flags)
        self.admins = []      # (name_id, lat, lon, level)
        self.pois = []        # (name_id, lat, lon, category_u8)
        self.ways_named = 0
        self.nodes_addr = 0
        self.nodes_place = 0
        self.nodes_poi = 0
        self._t0 = time.time()
        self._last = self._t0

    def _in_bbox(self, lat, lon):
        if self.bbox is None:
            return True
        min_lon, min_lat, max_lon, max_lat = self.bbox
        return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon

    def _nid(self, display):
        key = display
        if key in self.name_to_id:
            return self.name_to_id[key]
        i = len(self.names)
        self.names.append(display)
        self.name_to_id[key] = i
        return i

    def _progress(self, tag):
        now = time.time()
        if now - self._last < 20:
            return
        self._last = now
        print("... %s streets=%d addrs=%d admins=%d pois=%d names=%d (%.0fs)" % (
            tag, len(self.street_merge), len(self.addrs), len(self.admins),
            len(self.pois), len(self.names), now - self._t0), flush=True)

    def _get_poi_category(self, tags):
        # amenity
        am = tags.get("amenity")
        if am in POI_CATEGORIES:
            return POI_CATEGORIES[am]
        # shop
        sh = tags.get("shop")
        if sh in POI_CATEGORIES:
            return POI_CATEGORIES[sh]
        # tourism
        to = tags.get("tourism")
        if to in POI_CATEGORIES:
            return POI_CATEGORIES[to]
        # emergency
        em = tags.get("emergency")
        if em in POI_CATEGORIES:
            return POI_CATEGORIES[em]
        # building
        bu = tags.get("building")
        if bu in POI_CATEGORIES:
            return POI_CATEGORIES[bu]
        # man_made
        mm = tags.get("man_made")
        if mm in POI_CATEGORIES:
            return POI_CATEGORIES[mm]
        # office
        of = tags.get("office")
        if of in POI_CATEGORIES:
            return POI_CATEGORIES[of]
        return 0

    def node(self, n):
        tags = {t.k: t.v for t in n.tags}
        if not n.location.valid():
            return
        lat = n.location.lat
        lon = n.location.lon
        if not self._in_bbox(lat, lon):
            return

        # Address
        house = (tags.get("addr:housenumber") or "").strip()
        street = (tags.get("addr:street") or tags.get("addr:place") or "").strip()
        if house and street:
            for prefix in ("Đường ", "đường ", "Duong ", "duong "):
                if street.startswith(prefix):
                    street = street[len(prefix):].strip()
                    break
            nid = self._nid(street)
            hn = normalize_vi(house).replace(" ", "")
            if not hn:
                hn = house.lower()
            self.addrs.append((nid, hn, lat, lon, 0))
            self.nodes_addr += 1
            self._progress("node")
            return

        # Place / admin-ish
        pl = tags.get("place")
        if pl in PLACE_LEVEL:
            nm = place_name(tags)
            if not nm:
                return
            nid = self._nid(nm)
            self.admins.append((nid, lat, lon, PLACE_LEVEL[pl]))
            self.nodes_place += 1
            self._progress("node")
            return

        # POI (node)
        cat = self._get_poi_category(tags)
        if cat:
            nm = place_name(tags)
            if nm:
                nid = self._nid(nm)
                self.pois.append((nid, lat, lon, cat))
                self.nodes_poi += 1
                self._progress("node")

    def way(self, w):
        tags = {t.k: t.v for t in w.tags}
        hw = tags.get("highway")
        if hw not in HIGHWAY:
            # addr on building way
            house = (tags.get("addr:housenumber") or "").strip()
            street = (tags.get("addr:street") or "").strip()
            if house and street and len(w.nodes) > 0:
                la = lo = 0.0
                c = 0
                hit = self.bbox is None
                for nd in w.nodes:
                    if nd.location.valid():
                        if self._in_bbox(nd.location.lat, nd.location.lon):
                            hit = True
                        la += nd.location.lat
                        lo += nd.location.lon
                        c += 1
                if c > 0 and hit:
                    for prefix in ("Đường ", "đường ", "Duong ", "duong "):
                        if street.startswith(prefix):
                            street = street[len(prefix):].strip()
                            break
                    nid = self._nid(street)
                    hn = normalize_vi(house).replace(" ", "") or house.lower()
                    self.addrs.append((nid, hn, la / c, lo / c, 0))
                    self.nodes_addr += 1
            return

        name = road_name(tags)
        if not name:
            return
        la = lo = 0.0
        c = 0
        hit = self.bbox is None
        for nd in w.nodes:
            if nd.location.valid():
                if self._in_bbox(nd.location.lat, nd.location.lon):
                    hit = True
                la += nd.location.lat
                lo += nd.location.lon
                c += 1
        if c < 2 or not hit:
            return
        lat = la / c
        lon = lo / c
        nid = self._nid(name)
        by = int(lat * 50)
        bx = int(lon * 50)
        key = (nid, by, bx)
        cur = self.street_merge.get(key)
        if cur is None:
            self.street_merge[key] = [nid, lat, lon, 1, 0]
        else:
            n = cur[3] + 1
            cur[1] = (cur[1] * cur[3] + lat) / n
            cur[2] = (cur[2] * cur[3] + lon) / n
            cur[3] = n
        self.ways_named += 1
        self._progress("way")

        # POI (way) — e.g. building=*, shop=*
        cat = self._get_poi_category(tags)
        if cat:
            nm = place_name(tags)
            if nm:
                nid = self._nid(nm)
                self.pois.append((nid, lat, lon, cat))
                self.nodes_poi += 1


def finalize(handler):
    # street_merge: key -> [name_id, lat, lon, count, unused]
    # Houses (addrs) gắn vào street cùng name_id gần nhất trong build_search_bin.
    streets = []
    for _k, v in handler.street_merge.items():
        name_id, lat, lon = v[0], v[1], v[2]
        display = handler.names[name_id] if 0 <= name_id < len(handler.names) else ""
        streets.append((name_id, lat, lon, display, []))

    print("==> Finalize streets=%d addrs=%d admins=%d pois=%d names=%d" % (
        len(streets), len(handler.addrs), len(handler.admins),
        len(handler.pois), len(handler.names)), flush=True)

    return build_search_bin(
        handler.names,
        streets,
        handler.addrs,
        handler.admins,
        token_map=None,
        pois=handler.pois
    )


def main():
    ap = argparse.ArgumentParser(description="OSM PBF → search.bin GNS3")
    ap.add_argument("pbf", help="vietnam.osm.pbf")
    ap.add_argument("out_bin")
    add_common_args(ap)
    args = ap.parse_args()
    bbox, pbfs, _provinces = resolve_bbox_and_pbfs(args)

    out_dir = os.path.dirname(os.path.abspath(args.out_bin))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    t0 = time.time()
    h = SearchHandler(bbox=bbox)
    for pbf in pbfs:
        print("==> Scanning", pbf, flush=True)
        h.apply_file(pbf, locations=True)
    print("==> Scan done ways_named=%d addr=%d place=%d poi=%d (%.0fs)" % (
        h.ways_named, h.nodes_addr, h.nodes_place, h.nodes_poi, time.time() - t0), flush=True)

    data = finalize(h)
    with open(args.out_bin, "wb") as f:
        f.write(data)
    mb = len(data) / (1024 * 1024.0)
    print("==> Wrote %s size=%.1f MB in %.0fs" % (args.out_bin, mb, time.time() - t0), flush=True)
    print("    Magic: GNS3 — ready for app (OfflineGeocoder)", flush=True)


if __name__ == "__main__":
    main()