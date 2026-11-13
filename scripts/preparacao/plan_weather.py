# Input: geographic file path and identifier column, given on the command line.
# Output: weather_extents.json when --id-column is given; does not download weather or compute basin rain.

"""Prepare rectangular weather download extents from real basin geometries.

Optional spatial dependencies required. This does not compute basin averages.
"""
import argparse
import json
from pathlib import Path

# DATA_DIR: configurable data folder (ENERGY_DATA_DIR), defined in the acquisition core.
# Scripts in this subfolder reuse the modules in scripts/ (acquire, pipeline...).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from acquire import DATA_DIR


def main():
    import geopandas as gpd

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("polygons", help="Shapefile, GPKG or zip://ABSOLUTE_PATH_TO_ZIP")
    parser.add_argument("--id-column", help="Omit to inspect columns, CRS and bounds only")
    parser.add_argument("--output", type=Path, default=DATA_DIR / "geography/weather_extents.json")
    args = parser.parse_args()
    frame = gpd.read_file(args.polygons)
    if frame.crs is None:
        raise ValueError("Source CRS absent; do not assume EPSG:4326")
    if frame.empty or frame.geometry.isna().any() or frame.geometry.is_empty.any() or not frame.geometry.is_valid.all():
        raise ValueError("Empty, missing or invalid source geometries; inspect before planning")
    print(json.dumps({"columns": list(frame.columns), "source_crs": str(frame.crs),
                      "features": len(frame)}, ensure_ascii=False))
    if not args.id_column:
        return
    if args.id_column not in frame.columns:
        raise ValueError("ID column not found; inspect printed columns")
    if frame[args.id_column].isna().any() or frame[args.id_column].duplicated().any():
        raise ValueError("Basin IDs must be present and unique")
    wgs84 = frame.to_crs("EPSG:4326")
    output = {"source": args.polygons, "source_crs": str(frame.crs),
              "bbox_order": "west,south,east,north", "regions": [
                  {"id": str(row[args.id_column]), "bbox": list(row.geometry.bounds)}
                  for _, row in wgs84.iterrows()],
              "note": "Rectangles include cells outside the basin. Polygon intersection and area weights remain a separate step."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
