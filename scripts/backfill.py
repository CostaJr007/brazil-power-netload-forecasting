r"""Historical backfill: builds the PLAN (default) and downloads only with --execute.

Why separate from the daily pipeline?
- The daily pipeline looks only at recent days; models and backtests need years.
- A backfill takes hours. It uses another lock (data/backfill.lock), so the scheduled daily collection keeps running.
- The plan shows how many files and bytes will be downloaded BEFORE downloading.

Examples (PowerShell, project root):
    .\.venv\Scripts\python.exe scripts/backfill.py --sources ons,load --start 2018-01-01             # plan only
    .\.venv\Scripts\python.exe scripts/backfill.py --sources ons,load --start 2018-01-01 --execute   # run the plan
    .\.venv\Scripts\python.exe scripts/backfill.py --sources merge --start 2025-01-01 --end 2025-12-31
    .\.venv\Scripts\python.exe scripts/backfill.py --sources inmet --start 2018-01-01 --end 2025-12-31 --execute

GFS has no backfill: NOMADS keeps only ~10 days. Archived forecasts come from Open-Meteo Previous Runs.
"""
import argparse
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from urllib.request import Request, urlopen

from acquire import DATA_DIR, ROOT, atomic_json, json_get, utcnow
from discover_weather import listing
from pipeline import LOAD_API, LockBusy, Pipeline, select_period, single_run

# Mean size observed per load-API response on 2026-11-10 (bytes per day of data).
LOAD_BYTES_PER_DAY = {"programada": 9_400, "verificada": 23_500}


def head_size(url):
    """Content-Length via HEAD; None when the server does not report it."""
    try:
        with urlopen(Request(url, method="HEAD", headers={"User-Agent": "EnergyDataStudy/0.2"}), timeout=30) as response:
            value = response.headers.get("Content-Length")
            return int(value) if value else None
    except Exception:
        return None


def months(start, end):
    """Split [start, end] into monthly blocks (the first and last may be partial)."""
    cursor = start
    while cursor <= end:
        following = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        yield cursor, min(following - timedelta(days=1), end)
        cursor = following


def plan_ons(datasets, start, end):
    """Yearly/monthly ONS catalog files covering the period (registries without a date are left out)."""
    items = []
    for name in datasets:
        payload = json_get("https://dados.ons.org.br/api/3/action/package_show?id=" + name)
        for resource in select_period(payload["result"]["resources"], start, end, include_undated=False):
            items.append({"source": "ons", "dataset": name, "resource_id": resource["id"], "url": resource["url"],
                          "context": resource, "bytes": head_size(resource["url"])})
    return items


def plan_load(areas, start, end):
    """One call per month, type and area: ~100x fewer requests than day by day."""
    items = []
    for kind, codes in areas.items():
        for area in codes:
            for first, last in months(start, end):
                items.append({"source": "load", "kind": kind, "area": area, "start": first.isoformat(),
                              "end": last.isoformat(), "resource_id": f"{kind}_{area}_{first:%Y-%m}",
                              "bytes": LOAD_BYTES_PER_DAY[kind] * ((last - first).days + 1)})
    return items


def plan_merge(start, end):
    """Daily MERGE files; size estimated from a HEAD of the first file of each month."""
    items = []
    for first, last in months(start, end):
        base = f"https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/{first.year}/{first.month:02d}/"
        try:
            urls = listing(base)
        except Exception as exc:
            items.append({"source": "merge", "error": f"{base}: {exc}"})
            continue
        found = []
        for url in urls:
            match = re.search(r"MERGE_CPTEC_(\d{8})\.grib2$", url)
            if match and first <= datetime.strptime(match.group(1), "%Y%m%d").date() <= last:
                found.append((match.group(1), url))
        sample = head_size(found[0][1]) if found else None
        items += [{"source": "merge", "resource_id": stamp, "url": url, "bytes": sample} for stamp, url in sorted(found)]
    return items


def plan_inmet(start, end):
    """One yearly ZIP per year of the period, among those listed on the INMET page."""
    items = []
    for url in listing("https://portal.inmet.gov.br/dadoshistoricos"):
        match = re.search(r"/(20\d{2})\.zip$", url)
        if match and start.year <= int(match.group(1)) <= end.year:
            items.append({"source": "inmet", "resource_id": match.group(1), "url": url, "bytes": head_size(url)})
    return sorted(items, key=lambda i: i["resource_id"])


def summarize(items, start, end, sources):
    """Summary per source/dataset, to decide before downloading."""
    groups = {}
    for item in items:
        if "error" in item:
            continue
        key = item.get("dataset") or (f"carga-{item['kind']}" if item["source"] == "load" else item["source"])
        group = groups.setdefault(key, {"files": 0, "bytes_known": 0, "unknown_size": 0})
        group["files"] += 1
        if item.get("bytes"):
            group["bytes_known"] += item["bytes"]
        else:
            group["unknown_size"] += 1
    total = sum(g["bytes_known"] for g in groups.values())
    return {"planned_at": utcnow(), "start": start.isoformat(), "end": end.isoformat(), "sources": sources,
            "groups": groups, "total_files": sum(g["files"] for g in groups.values()), "total_bytes_known": total,
            "errors": [i["error"] for i in items if "error" in i],
            "note": "Load and MERGE bytes are estimates; ONS comes from each file's Content-Length. "
                    "Silver takes additional space (zstd Parquet, usually smaller than the source)."}


def write_plan(summary):
    atomic_json(ROOT / "docs/inventory/backfill_plan.json", summary)
    lines = ["# Historical backfill plan", "",
             f"Generated at {summary['planned_at']}. Period: {summary['start']} to {summary['end']}. Sources: {', '.join(summary['sources'])}.", "",
             "| Dataset | Files/calls | Known size (MB) | Without size |", "|---|---:|---:|---:|"]
    for name, group in sorted(summary["groups"].items()):
        lines.append(f"| {name} | {group['files']} | {group['bytes_known'] / 1e6:,.1f} | {group['unknown_size']} |")
    lines += ["", f"**Total:** {summary['total_files']} files/calls, ~{summary['total_bytes_known'] / 1e9:,.2f} GB known.", "",
              summary["note"], ""]
    if summary["errors"]:
        lines += ["Planning errors:", ""] + [f"- {e}" for e in summary["errors"]]
    (ROOT / "docs/inventory/backfill_plan.md").write_text("\n".join(lines), encoding="utf-8")


def execute(items, config, contracts, log):
    """Download and process item by item; one failure does not stop the others."""
    pipeline = Pipeline(DATA_DIR, config, contracts)
    pipeline.report["kind"] = "backfill"
    done = 0
    try:
        for index, item in enumerate(i for i in items if "error" not in i):
            try:
                if item["source"] == "ons":
                    manifest = pipeline.obtain("ons", item["dataset"], item["resource_id"], item["url"], item["context"],
                                               config["ons"]["max_file_mb"] * 1_000_000)
                    pipeline.transform(manifest)
                elif item["source"] == "load":
                    first, last = date.fromisoformat(item["start"]), date.fromisoformat(item["end"])
                    manifest, rows = pipeline.fetch_load(item["kind"], item["area"], first, last, item["resource_id"], "backfill")
                    if not rows:
                        log.info("No data in the API for %s (outside the available history?)", item["resource_id"])
                        continue
                    pipeline.transform(manifest)
                elif item["source"] == "inmet":
                    manifest = pipeline.obtain("inmet", "automatic_stations_annual", item["resource_id"], item["url"],
                                               {"role": "station_observations"}, config["inmet"]["max_file_mb"] * 1_000_000)
                    pipeline.transform(manifest)
                else:
                    manifest = pipeline.obtain("inpe", "merge_daily", item["resource_id"], item["url"],
                                               {"role": "estimate", "reference": item["resource_id"]})
                    pipeline.transform(manifest)
                done += 1
            except Exception as exc:
                pipeline.error(f"backfill:{item.get('dataset') or item['source']}:{item['resource_id']}", exc)
            if index % 25 == 0:
                log.info("Progresso: %s itens processados", index + 1)
        pipeline.publish_current()
        try:
            import gold
            pipeline.report["gold"] = gold.refresh(log=log.info)
        except Exception as exc:
            pipeline.error("gold", exc)
        pipeline.report.update(completed_at=utcnow(), processed=done,
                               status="partial" if pipeline.report["errors"] else "success")
        # Separate report: does not overwrite runs/latest.json, which describes the daily collection.
        atomic_json(DATA_DIR / "runs" / f"backfill_{pipeline.run_id}.json", pipeline.report)
        return pipeline.report
    finally:
        pipeline.close()


def main():
    config = json.loads((ROOT / "configs/pipeline.json").read_text(encoding="utf-8"))
    contracts = json.loads((ROOT / "configs/ons_contracts.json").read_text(encoding="utf-8"))
    settings = config["backfill"]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", default="ons,load", help="ons, load, merge and/or inmet, comma-separated")
    parser.add_argument("--start", default=settings["default_start"])
    parser.add_argument("--end", default=None, help="Default: yesterday (UTC)")
    parser.add_argument("--datasets", default=None, help="ONS datasets; default in configs/pipeline.json → backfill")
    parser.add_argument("--execute", action="store_true", help="Without this option, only plans")
    parser.add_argument("--max-gb", type=float, default=10.0, help="Refuses to run plans larger than this")
    args = parser.parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else datetime.now(timezone.utc).date() - timedelta(days=1)
    if start > end:
        raise SystemExit("--start after --end")
    sources = args.sources.split(",")
    if set(sources) - {"ons", "load", "merge", "inmet"}:
        raise SystemExit("Valid sources: ons, load, merge, inmet")
    (DATA_DIR / "runs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(DATA_DIR / "runs/backfill.log", encoding="utf-8")])
    log = logging.getLogger("backfill")
    try:
        with single_run(DATA_DIR / "backfill.lock"):
            items = []
            if "ons" in sources:
                items += plan_ons(args.datasets.split(",") if args.datasets else settings["ons_datasets"], start, end)
            if "load" in sources:
                items += plan_load(settings["load_areas"], start, end)
            if "merge" in sources:
                items += plan_merge(start, end)
            if "inmet" in sources:
                items += plan_inmet(start, end)
            summary = summarize(items, start, end, sources)
            write_plan(summary)
            print(json.dumps({k: summary[k] for k in ("total_files", "total_bytes_known", "errors")}, ensure_ascii=False))
            if not args.execute:
                print("Plan saved to docs/inventory/backfill_plan.md. Nothing was downloaded; use --execute.")
                return 0
            if summary["total_bytes_known"] > args.max_gb * 1e9:
                raise SystemExit(f"Plan of {summary['total_bytes_known'] / 1e9:.1f} GB exceeds --max-gb {args.max_gb}.")
            report = execute(items, config, contracts, log)
            print(json.dumps({"status": report["status"], "processed": report["processed"],
                              "errors": len(report["errors"])}, ensure_ascii=False))
            return int(bool(report["errors"]))
    except LockBusy:
        raise SystemExit("Another backfill is already running.")


if __name__ == "__main__":
    raise SystemExit(main())
