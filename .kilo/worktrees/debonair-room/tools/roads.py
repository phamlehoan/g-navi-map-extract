#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI: OSM → roads_name.db + .rmap — implementation: roads/build.py"""
import os
import sys

_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from roads.build import main

if __name__ == "__main__":
    main()
