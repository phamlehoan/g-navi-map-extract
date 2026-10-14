#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI: OSM → regions.db — implementation: regions/build.py"""
import os
import sys

_TOOLS = os.path.dirname(os.path.abspath(__file__))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from regions.build import main

if __name__ == "__main__":
    main()
