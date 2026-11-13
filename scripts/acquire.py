# Input: command-line arguments and configs/ons.json. Output: data/catalog, data/bronze and SQLite.
# Note: catalog, fetch, ons-load and download --execute use the network; profile-csv is local.

"""Acquisition only. Standard library; never modifies source records.

Run from the repository root: python scripts/acquire.py --help
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path, PureWindowsPath
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
# Data folder (Bronze/Silver/Gold/state). Default: <project>/data. Can point to
# another drive with the ENERGY_DATA_DIR environment variable (e.g. D:\EnergyData\data).
DATA_DIR = Path(os.environ.get("ENERGY_DATA_DIR") or ROOT / "data")


def resolve_data_path(stored):
    """Find a file saved with an absolute path from another machine or drive.

    Manifests store absolute paths. If the data folder moved, the part from
    bronze/, silver/, gold/ etc. onwards is re-applied on top of DATA_DIR.
    """
    path = Path(stored)
    if path.exists():
        return path
    # PureWindowsPath splits on both \ and /, so a path saved on Windows
    # is also broken into parts correctly when the code runs on Linux (CI).
    parts = PureWindowsPath(str(stored)).parts
    for anchor in ("bronze", "silver", "gold", "geography", "catalog", "runs", "weather_catalog"):
        if anchor in parts:
            candidate = DATA_DIR.joinpath(*parts[parts.index(anchor):])
            if candidate.exists():
                return candidate
    return path


# utcnow: current UTC time as a string, to record when an operation happened.
def utcnow():
    return datetime.now(timezone.utc).isoformat()


# safe: turns a value into a short, path-safe name (for folder names, never for source records).
def safe(value):
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value))[:150] or "resource"


# open_http: opens an HTTP response for a URL and timeout, retrying only transient failures; callers close it with `with`.
def open_http(url, timeout=60, headers=None):
    if urlsplit(url).scheme not in {"http", "https"}:
        raise ValueError("Only HTTP(S) URLs are accepted")
    for attempt in range(3):
        try:
            return urlopen(Request(url, headers={"User-Agent": "EnergyDataStudy/0.2", **(headers or {})}), timeout=timeout)
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        # Wait 1 then 2 seconds between attempts.
        time.sleep(2 ** attempt)
    raise RuntimeError("HTTP retries exhausted")


# json_get: fetches a URL with open_http and returns the parsed JSON; may raise network or JSON errors.
def json_get(url):
    with open_http(url) as response:
        return json.load(response)


# atomic_json: writes JSON to a temporary file and only then publishes the final name, so readers never see a half-written file.
def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".part")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


# digest_file: SHA-256 of a file computed in blocks, without loading it all into memory.
def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# Store: SQLite connection plus file storage. Each instance represents one storage root.
class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "acquisition.sqlite")
        self.db.execute("""CREATE TABLE IF NOT EXISTS attempts (
            attempt_id TEXT PRIMARY KEY, started_at TEXT, completed_at TEXT,
            source TEXT, dataset TEXT, resource_id TEXT, url TEXT,
            status TEXT, sha256 TEXT, bytes INTEGER, path TEXT, detail TEXT)""")
        self.db.commit()

    # close: closes this instance's SQLite connection (never deletes the database or data).
    def close(self):
        self.db.close()

    # fetch: downloads bytes for (source, dataset, resource id, URL) within a size limit, preserves revisions, logs the attempt and returns a manifest. Content still needs semantic validation.
    def fetch(self, source, dataset, resource_id, url, max_bytes=100_000_000, context=None, ranges=None):
        # ranges: optional list of (offset, length). Used to download only some
        # messages of a global GRIB file (ECMWF Open Data publishes an index with these offsets).
        # The parts are written in sequence into a single Bronze object.
        attempt_id = uuid.uuid4().hex
        started = utcnow()
        folder = self.root / "bronze" / safe(source) / safe(dataset) / safe(resource_id)
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / (attempt_id + ".part")
        # Save the attempt before any I/O so interrupted executions remain visible.
        with self.db:
            self.db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (attempt_id, started, None, source, dataset, resource_id,
                             url, "started", None, 0, None, None))
        size = 0
        try:
            with temp.open("wb") as output:
                # Without ranges there is a single plain request (None); with ranges, one per part.
                for part in (ranges or [None]):
                    extra = {"Range": f"bytes={part[0]}-{part[0] + part[1] - 1}"} if part else None
                    with (open_http(url, headers=extra) if extra else open_http(url)) as response:
                        # A server that ignores Range would return the whole file with status 200.
                        if extra and getattr(response, "status", 206) != 206:
                            raise ValueError("Servidor ignorou o pedido de faixa de bytes (esperado HTTP 206)")
                        # Headers and final URL of the (last) response, for auditing.
                        headers = dict(response.headers.items())
                        final_url = response.geturl()
                        # Size announced by the server for this response; may be missing.
                        expected = response.headers.get("Content-Length")
                        if expected and size + int(expected) > max_bytes:
                            raise ValueError(f"Content-Length exceeds {max_bytes} bytes")
                        received = 0
                        # Read 1 MB blocks until the response ends.
                        while block := response.read(1024 * 1024):
                            received += len(block)
                            size += len(block)
                            if size > max_bytes:
                                raise ValueError(f"Download exceeds {max_bytes} bytes")
                            # Write the bytes as received; records are never interpreted or modified here.
                            output.write(block)
                        if expected and received != int(expected):
                            raise ValueError("Incomplete download (Content-Length mismatch)")
            if size == 0:
                raise ValueError("Empty response")
            prefix = temp.open("rb")
            with prefix:
                first = prefix.read(256).lstrip().lower()
            # Block/error pages do not always start with <html> (e.g. CCEE's firewall page starts with <meta>).
            # A text/html Content-Type also reveals a page instead of a data file.
            content_type = str(headers.get("Content-Type", "")).lower()
            if first.startswith((b"<!doctype html", b"<html", b"<meta", b"<head", b"<title", b"<body")) \
                    or content_type.startswith("text/html"):
                raise ValueError("Received HTML instead of a data file")
            digest = digest_file(temp)
            # Content-addressed: changes create new objects, identical content reuses one.
            target = folder / digest
            if target.exists():
                if digest_file(target) != digest:
                    raise ValueError("Existing object failed hash verification")
                temp.unlink()
                status = "unchanged"
            else:
                temp.replace(target)
                status = "downloaded"
            metadata = {"attempt_id": attempt_id, "started_at": started,
                        "ingested_at": utcnow(), "url": url, "final_url": final_url,
                        "headers": headers, "sha256": digest, "bytes": size,
                        "path": str(target), "source": source, "dataset": dataset,
                        "resource_id": resource_id, "status": status,
                        "context": context or {},
                        "note": "HTTP Last-Modified is not a historical publication timestamp."}
            atomic_json(folder / (attempt_id + ".manifest.json"), metadata)
            with self.db:
                self.db.execute("UPDATE attempts SET completed_at=?,status=?,sha256=?,bytes=?,path=? WHERE attempt_id=?",
                                (utcnow(), status, digest, size, str(target), attempt_id))
            return metadata
        except Exception as exc:
            temp.unlink(missing_ok=True)
            with self.db:
                self.db.execute("UPDATE attempts SET completed_at=?,status='error',bytes=?,detail=? WHERE attempt_id=?",
                                (utcnow(), size, str(exc), attempt_id))
            raise


# discover: queries the CKAN package list, resolves real URLs and returns metadata plus per-dataset errors. Does not download energy files.
def discover(base, selected):
    # package_list inventories all names without pagination drift; package_show
    # resolves actual resource URLs for the curated selection.
    listing = json_get(base + "package_list")
    if not listing.get("success"):
        raise RuntimeError("CKAN package_list failed")
    names = sorted(listing["result"])
    packages, errors = [], []
    for name in selected:
        if name not in names:
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            errors.append({"dataset": name, "error": "Not found in package_list"})
            continue
        try:
            payload = json_get(base + "package_show?" + urlencode({"id": name}))
            if not payload.get("success"):
                raise ValueError(str(payload.get("error")))
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            packages.append(payload["result"])
        except Exception as exc:
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            errors.append({"dataset": name, "error": str(exc)})
    return {"discovered_at": utcnow(), "method": "CKAN package_list + package_show",
            "all_dataset_names": names, "packages": packages, "errors": errors}


# resource_plan: returns a sorted list of eligible resources from the catalog and filters; no network. Dictionaries and data files are selected separately.
def resource_plan(catalog, datasets, fmt, contains, documents):
    rows = []
    for package in catalog["packages"]:
        if package["name"] not in datasets:
            continue
        for item in package.get("resources", []):
            label = str(item.get("name", ""))
            url = item.get("url", "")
            is_document = bool(re.search(r"dicion.rio|dicionario|dictionary", label, re.I))
            if documents != is_document:
                continue
            if fmt and str(item.get("format", "")).lower() != fmt.lower():
                continue
            if contains and contains.casefold() not in (label + " " + url).casefold():
                continue
            if urlsplit(url).scheme not in {"http", "https"}:
                continue
            # An API-labelled catalogue entry can point to Swagger, not observations.
            if str(item.get("format", "")).upper() == "API":
                continue
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            rows.append({"dataset": package["name"], "resource_id": item["id"],
                         "name": label, "format": item.get("format"), "url": url})
    return sorted(rows, key=lambda row: (row["dataset"], row["name"], row["resource_id"]))


# profile_csv: counts rows, empty cells, malformed rows and repeated keys of a local CSV. Strings such as 01 are preserved; the source is never cleaned.
def profile_csv(path, keys):
    # Full scan, source strings retained; no imputation, truncation or casting.
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        sample = stream.read(65536)
        stream.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        except csv.Error:
            raise ValueError("Delimiter uncertain; inspect source dictionary") from None
        reader = csv.DictReader(stream, dialect=dialect)
        columns = reader.fieldnames or []
        if not columns or len(columns) != len(set(columns)):
            raise ValueError("Empty or duplicate column names")
        if set(keys) - set(columns):
            raise ValueError("Requested keys absent from CSV")
        missing = dict.fromkeys(columns, 0)
        seen, duplicates, malformed, count = set(), 0, 0, 0
        for row in reader:
            count += 1
            malformed += int(None in row or any(row.get(c) is None for c in columns))
            for column in columns:
                missing[column] += int(row.get(column) in {None, ""})
            if keys:
                key = tuple(row.get(k) for k in keys)
                duplicates += int(key in seen)
                seen.add(key)
    return {"path": str(path), "sha256": digest_file(Path(path)), "rows": count,
            "columns": columns, "delimiter": dialect.delimiter, "empty_cells": missing,
            "malformed_rows": malformed, "key_columns": keys,
            "duplicate_keys": duplicates if keys else None,
            "limitations": "No physical bounds, timestamp coverage or business keys inferred. Empty means literal empty string only."}


# gfs_url: validates date, UTC cycle, lead and west/south/east/north box and returns a NOAA URL; building it does not guarantee the run is still available.
def gfs_url(day, cycle, lead, bbox):
    date.fromisoformat(day)
    if cycle not in {0, 6, 12, 18} or not 0 <= lead <= 384:
        raise ValueError("Invalid cycle or lead time")
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Expected bbox WEST SOUTH EAST NORTH in degrees")
    params = {"file": f"gfs.t{cycle:02d}z.pgrb2.0p25.f{lead:03d}",
              "dir": f"/gfs.{day.replace('-', '')}/{cycle:02d}/atmos",
              "subregion": "", "leftlon": west, "rightlon": east,
              "bottomlat": south, "toplat": north,
              "var_UGRD": "on", "var_VGRD": "on", "var_TMP": "on",
              "var_PRES": "on", "var_APCP": "on", "var_DSWRF": "on",
              "lev_100_m_above_ground": "on", "lev_10_m_above_ground": "on",
              "lev_2_m_above_ground": "on", "lev_surface": "on"}
    return "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?" + urlencode(params)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    commands = parser.add_subparsers(dest="command", required=True)
    cat = commands.add_parser("catalog", help="Discover ONS datasets and resource URLs")
    cat.add_argument("--config", type=Path, default=ROOT / "configs/ons.json")
    cat.add_argument("--all-details", action="store_true", help="Resolve every dataset, not only curated ones")
    dl = commands.add_parser("download", help="Preview selected ONS resources; --execute downloads")
    dl.add_argument("--dataset", action="append", required=True)
    dl.add_argument("--format", default="CSV")
    dl.add_argument("--contains", default="")
    dl.add_argument("--documents", action="store_true")
    dl.add_argument("--limit", type=int, default=1, help="Max files TOTAL; no implicit bulk history")
    dl.add_argument("--max-mb", type=int, default=100)
    dl.add_argument("--execute", action="store_true")
    fetch = commands.add_parser("fetch", help="Download an explicit public URL (incl. API JSON)")
    fetch.add_argument("--url", required=True)
    fetch.add_argument("--source", required=True)
    fetch.add_argument("--dataset", required=True)
    fetch.add_argument("--resource-id", required=True)
    fetch.add_argument("--max-mb", type=int, default=100)
    profile = commands.add_parser("profile-csv")
    profile.add_argument("path", type=Path)
    profile.add_argument("--key", action="append", default=[])
    gfs = commands.add_parser("gfs", help="Preview a NOAA rectangular subset; --execute downloads")
    gfs.add_argument("--date", required=True)
    gfs.add_argument("--cycle", type=int, required=True)
    gfs.add_argument("--lead", type=int, required=True)
    gfs.add_argument("--bbox", type=float, nargs=4, required=True)
    gfs.add_argument("--execute", action="store_true")
    load = commands.add_parser("ons-load", help="Fetch one daily window of ONS load API JSON; area code from source required")
    load.add_argument("--kind", choices=["programada", "verificada"], required=True)
    load.add_argument("--date", required=True)
    load.add_argument("--area", required=True, help="Official cod_areacarga; not inferred from subsystem")
    args = parser.parse_args()
    if args.command == "catalog":
        config = json.loads(args.config.read_text(encoding="utf-8"))
        selected = config["selected"]
        if args.all_details:
            selected = json_get(config["catalog_url"] + "package_list")["result"]
        result = discover(config["catalog_url"], selected)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        atomic_json(args.data_dir / "catalog" / (stamp + ".json"), result)
        atomic_json(args.data_dir / "catalog" / "latest.json", result)
        print(json.dumps({"all_datasets": len(result["all_dataset_names"]),
                          "resolved": len(result["packages"]), "errors": result["errors"]}, ensure_ascii=False))
        return int(bool(result["errors"]))
    if args.command == "profile-csv":
        result = profile_csv(args.path, args.key)
        output = args.data_dir / "reports" / (result["sha256"] + ".profile.json")
        atomic_json(output, result)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    store = Store(args.data_dir)
    try:
        if args.command == "ons-load":
            date.fromisoformat(args.date)
            url = f"https://apicarga.ons.org.br/prd/carga{args.kind}?" + urlencode(
                {"dat_inicio": args.date, "dat_fim": args.date, "cod_areacarga": args.area})
            item = store.fetch("ons", f"carga-energia-{args.kind}",
                               f"{args.area}_{args.date}", url,
                               context={"area": args.area, "date": args.date,
                                        "semantic_validation": "pending: inspect JSON envelope and source documentation"})
            payload = json.loads(Path(item["path"]).read_text(encoding="utf-8-sig"))
            print(json.dumps({"manifest": item, "json_type": type(payload).__name__,
                              "note": "HTTP 200 / valid JSON alone do not establish observation completeness."}))
            return 0
        if args.command == "download":
            if args.limit < 1 or args.max_mb < 1:
                raise ValueError("limit and max-mb must be positive")
            catalog = json.loads((args.data_dir / "catalog/latest.json").read_text(encoding="utf-8"))
            known = {p["name"] for p in catalog["packages"]}
            if set(args.dataset) - known:
                raise ValueError("Dataset not resolved in catalog; run catalog first")
            plan = resource_plan(catalog, args.dataset, args.format, args.contains, args.documents)
            if not plan:
                raise ValueError("No resource matches filters; inspect catalog")
            print(json.dumps({"matched": len(plan), "selected": plan[:args.limit]}, ensure_ascii=False))
            failures = 0
            if args.execute:
                for item in plan[:args.limit]:
                    try:
                        print(json.dumps(store.fetch("ons", item["dataset"], item["resource_id"], item["url"], args.max_mb * 1_000_000, item)))
                    except Exception as exc:
                        failures += 1
                        print(f"ERROR {item['resource_id']}: {exc}", file=sys.stderr)
            return int(bool(failures))
        if args.command == "gfs":
            url = gfs_url(args.date, args.cycle, args.lead, args.bbox)
            print(url)
            if args.execute:
                item = store.fetch("noaa", "gfs", f"{args.date}_{args.cycle:02d}_f{args.lead:03d}", url,
                                   context={"bbox": args.bbox, "run_date": args.date,
                                            "cycle_utc": args.cycle, "lead_hours": args.lead,
                                            "geometry": "rectangle, not a basin polygon"})
                with Path(item["path"]).open("rb") as stream:
                    if stream.read(4) != b"GRIB":
                        raise ValueError("NOAA response is not GRIB; inspect manifest before use")
                print(json.dumps(item))
            return 0
        if args.max_mb < 1:
            raise ValueError("max-mb must be positive")
        print(json.dumps(store.fetch(args.source, args.dataset, args.resource_id, args.url, args.max_mb * 1_000_000)))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
