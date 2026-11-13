"""Download a first weather batch and document its content, without modelling.

Prerequisite: run discover_weather.py. By default: seven MERGE days,
three GFS leads and the current yearly INMET ZIP. Bytes go to Bronze.
"""
# CLI controla o tamanho inicial da coleta e permite repetir o procedimento.
import argparse
import csv
import io
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZipFile

# ecCodes reads GRIB messages; NumPy checks values without changing the file.
import eccodes
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import is_valid_reason

# Reuses the existing audit, writing and URL generation.
# Scripts in this subfolder reuse the modules in scripts/ (acquire, pipeline...).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from acquire import DATA_DIR, ROOT, Store, atomic_json, gfs_url, utcnow
from discover_weather import listing


def grib_inventory(path):
    """Read GRIB messages and record variable, unit, run and accumulation."""
    messages = []
    # A GRIB file may contain several messages with different levels and intervals.
    with Path(path).open("rb") as stream:
        while True:
            handle = eccodes.codes_grib_new_from_file(stream)
            if handle is None:
                break
            try:
                record = {}
                # startStep/endStep matter: APCP at f024 does not
                # automatically mean rain accumulated since the start of the run.
                keys = ["shortName", "name", "units", "typeOfLevel", "level",
                        "dataDate", "dataTime", "validityDate", "validityTime",
                        "stepType", "startStep", "endStep", "stepUnits", "gridType",
                        "Ni", "Nj", "iDirectionIncrementInDegrees", "jDirectionIncrementInDegrees",
                        "numberOfDataPoints", "numberOfMissing"]
                for key in keys:
                    try:
                        record[key] = eccodes.codes_get(handle, key)
                    except eccodes.CodesInternalError:
                        record[key] = None
                values = eccodes.codes_get_values(handle)
                # missingValue is a sentinel; a finite number may still mean missing.
                missing = eccodes.codes_get(handle, "missingValue")
                good = np.isfinite(values) & (values != missing)
                record["valid_values"] = int(good.sum())
                record["min_value"] = float(values[good].min()) if good.any() else None
                record["max_value"] = float(values[good].max()) if good.any() else None
                lats = eccodes.codes_get_array(handle, "latitudes")
                lons = eccodes.codes_get_array(handle, "longitudes")
                # Standardisation only in the report: GRIB bytes and coordinates are preserved.
                signed_lons = (lons + 180) % 360 - 180
                record["bbox_wgs84"] = [float(signed_lons.min()), float(lats.min()),
                                         float(signed_lons.max()), float(lats.max())]
                messages.append(record)
            finally:
                # Each message uses native memory and must be released every iteration.
                eccodes.codes_release(handle)
    if not messages:
        raise ValueError("File without decodable GRIB messages")
    return messages


def inspect_basins(discovery):
    """Publica apenas metadados espaciais e motivos de invalidez da origem."""
    frame = gpd.read_file("zip://" + discovery["basins"]["access_copy"].replace("\\", "/"))
    frame = frame.to_crs("EPSG:4326")
    frame["source_geometry_valid"] = frame.geometry.is_valid
    frame["source_geometry_reason"] = frame.geometry.map(is_valid_reason)
    folder = DATA_DIR / "geography"
    # GeoParquet is a registry/inspection product; it does not fix the original geometry.
    frame.to_parquet(folder / "ons_basins_inspected.parquet", index=False)
    fields = ["ID", "Nome_Bacia", "source_geometry_valid", "source_geometry_reason"]
    details = frame[fields].to_dict("records")
    atomic_json(folder / "ons_basins_quality.json", details)
    return frame, details


def station_inventory(manifest, basins):
    """Read station metadata inside the INMET ZIP, keeping a reference to the member."""
    stations, errors = [], []
    with ZipFile(manifest["path"]) as archive:
        members = [m for m in archive.namelist() if m.lower().endswith(".csv")]
        for member in members:
            try:
                with archive.open(member) as stream:
                    # The first eight records hold the registry, not hourly observations.
                    lines = [stream.readline().decode("latin-1").strip() for _ in range(8)]
                meta = {}
                for line in lines:
                    key, value = line.split(";", 1)
                    meta[key.rstrip(":").strip()] = value.strip(";").strip()
                lat = float(meta["LATITUDE"].replace(",", "."))
                lon = float(meta["LONGITUDE"].replace(",", "."))
                stations.append({"member": member, "station_code": meta.get("CODIGO (WMO)", ""),
                                 "name": meta.get("ESTACAO", ""), "uf": meta.get("UF", ""),
                                 "latitude": lat, "longitude": lon, "metadata": meta})
            except Exception as exc:
                errors.append({"member": member, "error": str(exc)})
        # Read one full member to check the reference and sentinels as a sample.
        example = None
        if stations:
            member = stations[0]["member"]
            with archive.open(member) as stream:
                reader = csv.reader(io.TextIOWrapper(stream, encoding="latin-1"), delimiter=";")
                for _ in range(8):
                    next(reader)
                header = next(reader)
                dates, rows, sentinel_cells = [], 0, 0
                for row in reader:
                    if not row:
                        continue
                    rows += 1
                    dates.append(row[0])
                    sentinel_cells += sum(v.strip() in {"-9999", "-9999,0", "-9999.0"} for v in row)
                example = {"member": member, "header": header, "rows": rows,
                           "min_reference_text": min(dates) if dates else None,
                           "max_reference_text": max(dates) if dates else None,
                           "sentinel_cells": sentinel_cells,
                           "scope": "Only one member; does not certify coverage of every station."}
    if not stations:
        raise ValueError("No station record was read; check the INMET encoding/header")
    table = pd.DataFrame(stations)
    # Intersect only valid geometries; the six invalid ones are not repaired here.
    points = gpd.GeoDataFrame(table.drop(columns="metadata"),
                             geometry=gpd.points_from_xy(table.longitude, table.latitude), crs="EPSG:4326")
    valid = basins.loc[basins.source_geometry_valid, ["ID", "Nome_Bacia", "geometry"]]
    matches = gpd.sjoin(points, valid, how="left", predicate="intersects")
    matches.drop(columns="geometry").to_parquet(DATA_DIR / "geography/inmet_stations_basin_candidates.parquet", index=False)
    atomic_json(DATA_DIR / "geography/inmet_station_inventory.json", {"stations": stations, "errors": errors})
    return {"csv_members": len(members), "stations_read": len(stations), "metadata_errors": errors,
            "stations_intersecting_valid_basins": int(matches.loc[matches.ID.notna(), "member"].nunique()),
            "spatial_limit": "Candidate join with valid basins only; no link does not mean the station is outside every basin.",
            "sample_observations": example}


def main():
    """Organise the batch, preserve originals and publish evidence after each file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="Number of daily MERGE files")
    parser.add_argument("--skip-inmet", action="store_true", help="Skip the yearly ZIP on repeat runs")
    args = parser.parse_args()
    if not 1 <= args.days <= 31:
        raise ValueError("Use 1 to 31 days in this initial batch")
    discovery = json.loads((ROOT / "docs/inventory/weather_discovery.json").read_text(encoding="utf-8"))
    basins, quality = inspect_basins(discovery)
    west, south, east, north = discovery["basins"]["bbox"]
    # Round outwards and add a grid margin: this is not a polygon clip.
    bbox = [math.floor(west * 4) / 4 - .25, math.floor(south * 4) / 4 - .25,
            math.ceil(east * 4) / 4 + .25, math.ceil(north * 4) / 4 + .25]
    report = {"started_at": utcnow(), "collection": "initial_weather_acquisition",
              "basin_quality": quality, "forecast_bbox": bbox, "files": [], "errors": []}
    store = Store(DATA_DIR)
    report_path = ROOT / "docs/inventory/weather_acquisition.json"

    def collect(source, dataset, resource_id, url, context, kind="grib", limit=100_000_000):
        """Download via Store and separate HTTP success from decoding success."""
        entry = {"source": source, "dataset": dataset, "url": url}
        try:
            meta = store.fetch(source, dataset, resource_id, url, limit, context=context)
            entry["manifest"] = meta
            if kind == "grib":
                entry["messages"] = grib_inventory(meta["path"])
            elif kind == "inmet":
                entry["station_inventory"] = station_inventory(meta, basins)
            elif kind == "text":
                entry["text"] = Path(meta["path"]).read_text(encoding="utf-8", errors="replace")
            entry["validation_status"] = "readable"
            print(f"OK {source}/{dataset}/{resource_id}", flush=True)
        except Exception as exc:
            entry["validation_status"] = "error"
            entry["error"] = str(exc)
            report["errors"].append({"source": source, "resource_id": resource_id, "error": str(exc)})
            print(f"ERROR {source}/{resource_id}: {exc}", flush=True)
        report["files"].append(entry)
        atomic_json(report_path, report)

    try:
        links = discovery["sources"]["merge_month"]["links"]
        daily = sorted(u for u in links if u.endswith(".grib2"))[-args.days:]
        for url in daily:
            stamp = re.search(r"(\d{8})\.grib2$", url).group(1)
            collect("inpe", "merge_daily", stamp, url,
                    {"role": "gridded_precipitation_estimate", "file_reference": stamp,
                     "note": "Accumulation will be interpreted with the CTL and documentation, not just the name."})
        if daily:
            # The CTL file and manual document the grid and the rain accumulation convention.
            ctl = daily[-1].replace(".grib2", ".ctl")
            collect("inpe", "merge_documentation", "latest_ctl", ctl, {"role": "product_metadata"}, "text")
        manuals = [u for u in discovery["sources"]["merge_root"]["links"] if u.endswith("MERGE_READ-ME.pdf")]
        for url in manuals:
            collect("inpe", "merge_documentation", "readme", url, {"role": "documentation"}, "binary")

        # Confirm each lead is available in a real NOAA directory.
        run_urls = discovery["sources"]["gfs_root"]["links"]
        chosen = None
        for run in sorted(run_urls, reverse=True)[:3]:
            day = re.search(r"gfs\.(\d{8})", run).group(1)
            try:
                files = listing(run + "00/atmos/")
                if all(any(u.endswith(f"gfs.t00z.pgrb2.0p25.f{lead:03d}") for u in files) for lead in [24, 48, 72]):
                    chosen = datetime.strptime(day, "%Y%m%d").date().isoformat()
                    break
            except Exception as exc:
                report["errors"].append({"source": "gfs_discovery", "url": run, "error": str(exc)})
        if chosen is None:
            raise ValueError("No GFS 00 UTC run with all three leads was confirmed")
        for lead in [24, 48, 72]:
            collect("noaa", "gfs_0p25", f"{chosen}_00_f{lead:03d}", gfs_url(chosen, 0, lead, bbox),
                    {"role": "forecast", "run_date": chosen, "cycle_utc": 0,
                     "lead_hours": lead, "requested_bbox": bbox,
                     "note": "Rectangular grid; startStep/endStep specific to each variable."})
        if not args.skip_inmet:
            annual = discovery["sources"]["inmet"]["links"]
            candidates = [u for u in annual if re.search(r"/20\d{2}\.zip$", u)]
            latest = max(candidates, key=lambda u: re.search(r"(20\d{2})\.zip$", u).group(1))
            collect("inmet", "automatic_stations_annual", Path(urlsplit(latest).path).stem,
                    latest, {"role": "station_observations", "selection": "latest_annual_zip_announced"},
                    "inmet", limit=500_000_000)
    finally:
        store.close()
        report["completed_at"] = utcnow()
        atomic_json(report_path, report)
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
