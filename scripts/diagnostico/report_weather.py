"""Inspect the local weather batch and publish an acquisition summary.

Does not download data, fix values or compute forecasts or basin means.
"""
import json
import re
from pathlib import Path

# pypdf reads the technical documentation; ecCodes has already inspected the GRIB files.
from pypdf import PdfReader

# Scripts in this subfolder reuse the modules in scripts/ (acquire, pipeline...).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from acquire import DATA_DIR, ROOT, atomic_json, utcnow


def main():
    """Relate the files received to metadata, limitations and documentation."""
    report_path = ROOT / "docs/inventory/weather_acquisition.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    files = report["files"]
    manual = next(f for f in files if f["dataset"] == "merge_documentation" and f["url"].endswith(".pdf"))
    # Extracted text only helps reading; the original PDF stays in Bronze.
    reader = PdfReader(manual["manifest"]["path"])
    pages = [page.extract_text() or "" for page in reader.pages]
    documentation = DATA_DIR / "weather_documentation"
    documentation.mkdir(parents=True, exist_ok=True)
    (documentation / "merge_manual.txt").write_text("\n\n".join(pages), encoding="utf-8")
    # Pages with key terms are recorded for human review of the intervals.
    relevant = [{"page": i + 1, "text": text} for i, text in enumerate(pages)
                if re.search(r"12.?UTC|12.?GMT|12.?Z|acumul|24 horas|estaç", text, re.I)]
    atomic_json(documentation / "merge_manual_relevant_pages.json", relevant)
    for page in relevant:
        # The console only gets an excerpt; the full text is saved locally.
        print(f"MANUAL page {page['page']}: {page['text'][:2000]}")

    rows = []
    for item in files:
        messages = item.get("messages", [])
        if item["dataset"] == "merge_daily":
            for message in messages:
                # O CTL do produto declara dois campos: PREC e NEST. Os nomes
                # generic ecCodes labels are kept and never used as the definition.
                if message["shortName"] == "rdp":
                    message["product_field_from_ctl"] = "PREC"
                    message["product_description_from_ctl"] = "Surface Precipitation [kg/m^2]"
                elif message["shortName"] == "prmsl":
                    message["product_field_from_ctl"] = "NEST"
                    message["product_description_from_ctl"] = "Number of Stations / Grid Point"
        if item["dataset"] == "gfs_0p25":
            # Check the fields actually received for the wind components.
            available = {(m["shortName"], m["typeOfLevel"], m["level"]) for m in messages}
            required = {("u", "heightAboveGround", 100), ("v", "heightAboveGround", 100),
                        ("10u", "heightAboveGround", 10), ("10v", "heightAboveGround", 10),
                        ("2t", "heightAboveGround", 2)}
            item["required_fields_missing"] = [list(k) for k in sorted(required - available)]
            if item["required_fields_missing"]:
                raise ValueError("GFS missing some of the essential requested fields")
        rows.append({"source": item["source"], "dataset": item["dataset"], "url": item["url"],
                     "validation": item["validation_status"], "bytes": item.get("manifest", {}).get("bytes"),
                     "sha256": item.get("manifest", {}).get("sha256"), "grib_messages": len(messages)})
    summary = {"checked_at": utcnow(), "files": len(files),
               "total_bytes": sum(r["bytes"] or 0 for r in rows),
               "errors": report["errors"], "resources": rows,
               "invalid_source_basins": [b for b in report["basin_quality"] if not b["source_geometry_valid"]]}
    report["summary"] = summary
    atomic_json(report_path, report)
    atomic_json(ROOT / "docs/inventory/weather_summary.json", summary)
    # The summary uses the references actually received, not dates fixed in the script.
    merge_files = [f for f in files if f["dataset"] == "merge_daily"]
    merge_dates = sorted(f["manifest"]["context"]["file_reference"] for f in merge_files)
    gfs_files = [f for f in files if f["dataset"] == "gfs_0p25"]
    gfs_context = gfs_files[0]["manifest"]["context"] if gfs_files else {}
    inmet_files = [f for f in files if f["source"] == "inmet"]
    station = inmet_files[0].get("station_inventory", {}) if inmet_files else {}
    sample = station.get("sample_observations") or {}
    invalid = summary["invalid_source_basins"]
    lines = ["# Weather: data actually acquired", "",
             f"Checked UTC: {summary['checked_at']}. Files: {len(files)}. Original bytes: {summary['total_bytes']:,}.", "",
             "| Origin | Product | File/query | Status |", "|---|---|---|---|"]
    for item in files:
        lines.append(f"| {item['source']} | {item['dataset']} | [source]({item['url']}) | {item['validation_status']} |")
    lines += ["", "## Content and scope", "",
              f"- MERGE: {len(merge_files)} daily files, references {merge_dates}, original 0.1° grid, with CTL and manual. The CTL declares PREC (precipitation) and NEST (number of stations per point); the generic rdp/prmsl labels do not define the product. Original metadata preserved.",
              f"- GFS: run {gfs_context.get('run_date')}, cycle {gfs_context.get('cycle_utc')} UTC; {len(gfs_files)} files for 24/48/72 h leads. 0.25° grid, basin bounding box with margin. Wind components at 10/100 m and 2 m temperature checked; pressure, precipitation and radiation are present.",
              f"- INMET: {station.get('csv_members')} CSV members; {station.get('stations_read')} station records read. Sampled member: {sample.get('member')}; references {sample.get('min_reference_text')} to {sample.get('max_reference_text')}. Does not certify uniform coverage of the other stations.",
              f"- Geography: {len(report['basin_quality'])} ONS features; {len(invalid)} invalid geometries. Candidate link of {station.get('stations_intersecting_valid_basins')} stations to valid basins. Invalid ones were excluded only from the spatial query; the original source is preserved.",
              "- MERGE manual of 2025-05-26: documents the new base built on IMERG V07B and history reprocessed since 1998. The same file naming does not guarantee the same processing version. The exact daily closing convention still needs confirmation before aggregating by calendar day.",
              "", "## Limits for the next stage", "",
              "This is an initial batch. The three GFS leads are spaced instants, not a continuous hourly forecast. The basin box does not guarantee coverage of every wind/solar plant; asset locations will be a separate registry.",
              "GFS precipitation contains messages with different startStep/endStep: select one message per interval before summing. Units were preserved, including Kelvin, Pa, kg/m², m/s and W/m². Mean radiation in W/m² is not directly the accumulated radiation in kJ/m² published by INMET.",
              "No basin rain means were computed, geometries repaired, gaps filled or values removed. Silver is a later stage. ERA5/CDS, GEFS, ECMWF and ANA have no acquisition run in this delivery yet.",
              "", "## Reproduzir", "", "```powershell",
              ".\\.venv\\Scripts\\python.exe scripts/discover_weather.py",
              ".\\.venv\\Scripts\\python.exe scripts/download_weather.py",
              ".\\.venv\\Scripts\\python.exe scripts/report_weather.py", "```", "",
              "Official listings were preserved in data/weather_catalog. Weather originals are in data/bronze/inpe, data/bronze/noaa and data/bronze/inmet, with manifests and SQLite history."]
    (ROOT / "docs/inventory/weather_acquisition.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"files": summary["files"], "bytes": summary["total_bytes"], "errors": summary["errors"]}))


if __name__ == "__main__":
    main()
