# AI Agent Rules

## Scratchpad Directory

**All test, analysis, and experimental code must be written to `analyze/`.**

- The `analyze/` directory is gitignored and never committed
- Use it for: debug scripts, one-off analysis, prototype code, test data exploration
- Do NOT write test/analysis files in the project root or source directories
- Clean up `analyze/` periodically; it's disposable workspace

## Output Directories

**Production output → `out/`**
- All production pack files go to `out/` (gitignored)
- Structure: `out/alert_data/`, `out/roads_map/`

**Test output → `out_test/`**
- Use `data_source/main-da-nang.osm.pbf` (1.4MB, Da Nang area) for fast testing
- Export test results to `out_test/` (gitignored)
- Clean up `out_test/` after verification

## Example

```
analyze/
  debug_routing.py
  test_province_extract.ipynb
  osm_data_inspection.py

out/                    # Production (gitignored)
  alert_data/
    regions.db
    roads_name.db
    speed_limit.db
    spds.db
    traffic_lights.db
    search.bin
  roads_map/
    viet_nam/
    bien_dong/

out_test/               # Test with main-da-nang.pbf (gitignored)
  alert_data/
  roads_map/
```