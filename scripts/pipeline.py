"""Daily pipeline: queries sources, keeps Bronze and publishes Silver snapshots and Gold views.

--offline processes only files already downloaded; without it the network is used.
Task Scheduler calls this program every 15 minutes; the cadence of each source lives in configs/pipeline.json.
"""
import argparse
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlsplit

from urllib.error import HTTPError

from acquire import DATA_DIR, ROOT, Store, atomic_json, digest_file, gfs_url, json_get, open_http, resolve_data_path, utcnow
from discover_weather import listing
from silver import LOAD_DATASETS, build_silver, parse_load_json

LOAD_API = "https://apicarga.ons.org.br/prd/carga{kind}?"


class LockBusy(Exception):
    """Another run already holds the lock; not a collection failure."""


@contextmanager
def single_run(path):
    """Process lock released by the operating system even after a crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LockBusy(f"Trava ocupada: {path}") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def file_period(url):
    """Period covered by the file name (year, year_month or year_month_day); None if there is no date."""
    # Also recognises 19xx: a 1999 file must not be mistaken for an undated registry.
    match = re.search(r"((?:19|20)\d{2})(?:[_-](\d{2}))?(?:[_-](\d{2}))?", urlsplit(url).path.rsplit("/", 1)[-1])
    if not match:
        return None
    year, month, day = (int(v) if v else None for v in match.groups())
    if month is None:
        return date(year, 1, 1), date(year, 12, 31)
    if day is None:
        following = date(year + month // 12, month % 12 + 1, 1)
        return date(year, month, 1), following - timedelta(days=1)
    return date(year, month, day), date(year, month, day)


def select_period(resources, start, end, include_undated=True, formats=("PARQUET",)):
    """Select files whose period intersects [start, end]; undated registries are optional."""
    chosen = {}
    wanted = {f.upper() for f in formats}
    for resource in resources:
        if str(resource.get("format", "")).upper() not in wanted:
            continue
        if re.search(r"dicion.rio", resource.get("name", ""), re.I):
            continue
        url = resource["url"]
        period = file_period(url)
        if period is None and not include_undated:
            continue
        if period and not (period[0] <= end and period[1] >= start):
            continue
        # The URL is the transfer identity; the resource ID stays in the context.
        chosen[url] = resource
    return sorted(chosen.values(), key=lambda r: r["url"])


def select_recent(resources, today, days):
    """Daily window: the last days, including month/year boundaries and the D+1 schedule."""
    return select_period(resources, today - timedelta(days=days), today + timedelta(days=1))


class Pipeline:
    """Operational and processing state; SQLite is not a distributed queue."""

    def __init__(self, root, config, contracts, force=False):
        self.root, self.config, self.contracts, self.force = Path(root), config, contracts, force
        self.store = Store(root)
        self.state = sqlite3.connect(self.root / "pipeline.sqlite", timeout=30)
        self.state.execute("CREATE TABLE IF NOT EXISTS tasks (name TEXT PRIMARY KEY, last_success TEXT)")
        self.state.execute("CREATE TABLE IF NOT EXISTS http (url TEXT PRIMARY KEY, fingerprint TEXT, manifest TEXT)")
        self.state.execute("CREATE TABLE IF NOT EXISTS snapshots (identity TEXT PRIMARY KEY, manifest TEXT, snapshot TEXT)")
        self.state.commit()
        # Changing a contract, quality threshold or Silver code produces a new transformation version.
        # Frequencies/notes from the config are NOT included: changing them must not reprocess Silver.
        # Normalised line endings: CRLF (Windows) and LF give the same version.
        code = (Path(__file__).parent / "silver.py").read_bytes().replace(b"\r\n", b"\n")
        relevant = [config["version"], config.get("max_invalid_fraction"), contracts,
                    config.get("ons_load", {}).get("contracts", {})]
        signature = hashlib.sha256(json.dumps(relevant, sort_keys=True).encode() + code).hexdigest()[:10]
        self.version = config["version"] + "-" + signature
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self.report = {"run_id": self.run_id, "started_at": utcnow(), "version": self.version,
                       "tasks": [], "errors": [], "snapshots": [], "blocked_sources": config["blocked_sources"]}
        self.log = logging.getLogger("pipeline")

    def close(self):
        self.state.close()
        self.store.close()

    def due(self, name, minutes):
        """The last success drives the cadence; an error does not postpone the next attempt."""
        row = self.state.execute("SELECT last_success FROM tasks WHERE name=?", (name,)).fetchone()
        # Half-a-tick tolerance avoids skipping a collection by a few seconds of difference
        # between the end of the previous run and a 15-minute scheduler trigger.
        threshold = minutes - min(self.config["scheduler_minutes"] / 2, minutes / 2)
        return self.force or row is None or datetime.now(timezone.utc) - datetime.fromisoformat(row[0]) >= timedelta(minutes=threshold)

    def task(self, name, minutes, function):
        """One source may fail without stopping the others; the global status becomes partial."""
        if not self.due(name, minutes):
            self.report["tasks"].append({"name": name, "status": "not_due"})
            return
        self.log.info("Iniciando %s", name)
        before = len(self.report["errors"])
        try:
            function()
        except Exception as exc:
            self.error(name, exc)
        failed = len(self.report["errors"]) > before
        self.report["tasks"].append({"name": name, "status": "failed" if failed else "success"})
        if not failed:
            with self.state:
                self.state.execute("INSERT OR REPLACE INTO tasks VALUES (?,?)", (name, utcnow()))

    def error(self, task, exc):
        self.log.error("%s: %s", task, exc)
        self.report["errors"].append({"task": task, "error": str(exc), "at": utcnow()})

    def previous_manifest(self, url):
        """Use the persisted state or look for an earlier acquisition in Bronze."""
        row = self.state.execute("SELECT fingerprint,manifest FROM http WHERE url=?", (url,)).fetchone()
        if row:
            return row[0], json.loads(row[1])
        candidates = []
        for path in (self.root / "bronze").rglob("*.manifest.json"):
            item = json.loads(path.read_text(encoding="utf-8"))
            if item["url"] == url and resolve_data_path(item["path"]).exists():
                candidates.append(item)
        if not candidates:
            return None, None
        # Compare with the MOST RECENT acquisition: comparing with the oldest
        # would re-download a file that already changed and was collected later.
        item = max(candidates, key=lambda m: m["ingested_at"])
        return self.fingerprint(item.get("headers", {})), item

    @staticmethod
    def fingerprint(headers):
        """ETag/Last-Modified validate changes; they are not record dates."""
        h = {k.lower(): str(v) for k, v in headers.items()}
        if not (h.get("etag") or h.get("last-modified")):
            return None
        return json.dumps([h.get("etag"), h.get("last-modified"), h.get("content-length")])

    def obtain(self, source, dataset, resource_id, url, context=None, limit=150_000_000, head=True, ranges=None):
        """HEAD before GET to avoid re-downloading unchanged files.

        Dynamic APIs (head=False) have no stable validator: always GET, and the
        content hash decides whether there was a revision.
        """
        old_fp, previous = self.previous_manifest(url)
        current_fp = None
        if head:
            try:
                with urlopen(Request(url, method="HEAD", headers={"User-Agent": "EnergyDataStudy/0.2"}), timeout=30) as response:
                    current_fp = self.fingerprint(dict(response.headers.items()))
            except Exception as exc:
                self.log.warning("HEAD unavailable; trying GET: %s (%s)", url, exc)
        if current_fp and current_fp == old_fp and previous and digest_file(resolve_data_path(previous["path"])) == previous["sha256"]:
            manifest = previous
            self.log.info("Unchanged: %s", dataset)
        else:
            manifest = self.store.fetch(source, dataset, resource_id, url, limit, context=context, ranges=ranges)
            # If the bytes are identical, keep the first proven availability.
            if previous and previous["sha256"] == manifest["sha256"]:
                manifest = {**manifest, "ingested_at": previous["ingested_at"]}
        with self.state:
            self.state.execute("INSERT OR REPLACE INTO http VALUES (?,?,?)",
                               (url, current_fp or self.fingerprint(manifest.get("headers", {})), json.dumps(manifest)))
        return manifest

    def transform(self, manifest):
        """Publish only snapshots that pass the contract; the last good one stays available."""
        dataset = manifest["dataset"]
        contract = self.contracts.get(dataset) or self.config.get("ons_load", {}).get("contracts", {}).get(dataset, {})
        discovery = json.loads((ROOT / "docs/inventory/weather_discovery.json").read_text(encoding="utf-8"))
        bbox = discovery["basins"]["bbox"]
        # Manifestos guardam caminho absoluto; se a pasta de dados mudou de disco, reencontra o arquivo.
        # (Done here and not in silver.py, because silver.py's code defines the Silver version.)
        resolved = str(resolve_data_path(manifest["path"]))
        if resolved != manifest["path"]:
            manifest = {**manifest, "path": resolved}
        snapshot = build_silver(self.root, manifest, contract, self.version, bbox, self.config["max_invalid_fraction"])
        summary = {"source": manifest["source"], "dataset": dataset, "status": snapshot["status"],
                   "valid_rows": snapshot["valid_rows"], "rejected_rows": snapshot["rejected_rows"]}
        self.report["snapshots"].append(summary)
        if snapshot["status"] != "published":
            raise ValueError(f"Quality check failed: {dataset}, invalid fraction={snapshot['invalid_fraction']:.3%}")
        # CSV and Parquet of the same logical file share the same current slot.
        # In the load API the URL path is the same for every area/day: the slot is the resource_id.
        by_file = manifest["source"] == "ons" and dataset not in LOAD_DATASETS
        slot = urlsplit(manifest["url"]).path.rsplit(".", 1)[0] if by_file else manifest["resource_id"]
        identity = f"{manifest['source']}|{dataset}|{slot}"
        with self.state:
            self.state.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?)",
                               (identity, json.dumps(manifest), json.dumps(snapshot)))
        self.log.info("Silver %s: %s valid, %s rejected", dataset, snapshot["valid_rows"], snapshot["rejected_rows"])

    def ons(self, only_hourly=False):
        """Query the live catalog and recent resources, including revisions from the last days."""
        names = ["dados_hidrologicos_ho"] if only_hourly else list(self.contracts)
        for name in names:
            if not only_hourly and name == "dados_hidrologicos_ho":
                continue
            interval = self.config["ons"]["hourly_hydro_interval_minutes" if only_hourly else "interval_minutes"]
            task_name = "ons_dataset:" + name
            if not self.due(task_name, interval):
                continue
            error_count = len(self.report["errors"])
            try:
                payload = json_get("https://dados.ons.org.br/api/3/action/package_show?id=" + name)
                if not payload.get("success"):
                    raise ValueError("Falha CKAN")
                package = payload["result"]
                # Preserve the discovery used in this run, without depending on yesterday's catalog.
                atomic_json(self.root / "catalog/pipeline" / self.run_id / (name + ".json"), payload)
                selected = select_recent(package["resources"], datetime.now(timezone.utc).date(), self.config["ons"]["lookback_days"])
                if not selected:
                    raise ValueError("Nenhum Parquet recente encontrado")
                for item in selected:
                    try:
                        manifest = self.obtain("ons", name, item["id"], item["url"], item,
                                               self.config["ons"]["max_file_mb"] * 1_000_000)
                        self.transform(manifest)
                    except Exception as exc:
                        self.error(name, exc)
            except Exception as exc:
                self.error(name, exc)
            if len(self.report["errors"]) == error_count:
                with self.state:
                    self.state.execute("INSERT OR REPLACE INTO tasks VALUES (?,?)", (task_name, utcnow()))

    def merge(self):
        """Fetch the last days, including month boundaries; missing D is not an error if D-1 exists."""
        today = datetime.now(timezone.utc).date()
        days = [today - timedelta(days=i) for i in range(self.config["merge"]["lookback_days"] + 1)]
        found = 0
        for year, month in sorted({(d.year, d.month) for d in days}):
            urls = listing(f"https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/{year}/{month:02d}/")
            stamps = {d.strftime("%Y%m%d") for d in days}
            for url in urls:
                match = re.search(r"MERGE_CPTEC_(\d{8})\.grib2$", url)
                if match and match.group(1) in stamps:
                    found += 1
                    self.transform(self.obtain("inpe", "merge_daily", match.group(1), url,
                                               {"role": "estimate", "reference": match.group(1)}))
        if not found:
            raise ValueError("MERGE: no recent file in the search window")

    def gfs(self):
        """Check cycles actually published; re-query to complete late leads."""
        today = datetime.now(timezone.utc).date()
        discovery = json.loads((ROOT / "docs/inventory/weather_discovery.json").read_text(encoding="utf-8"))
        west, south, east, north = discovery["basins"]["bbox"]
        bbox = [west - .5, south - .5, east + .5, north + .5]
        completed = 0
        for offset in range(self.config["gfs"]["lookback_days"] + 1):
            day = today - timedelta(days=offset)
            for cycle in self.config["gfs"]["cycles"]:
                if datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=cycle) > datetime.now(timezone.utc):
                    continue
                base = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.{day:%Y%m%d}/{cycle:02d}/atmos/"
                try:
                    urls = listing(base)
                except Exception as exc:
                    self.log.warning("Cycle not available yet: %s (%s)", base, exc)
                    continue
                for lead in self.config["gfs"]["leads"]:
                    if not any(u.endswith(f"gfs.t{cycle:02d}z.pgrb2.0p25.f{lead:03d}") for u in urls):
                        continue
                    manifest = self.obtain("noaa", "gfs_0p25", f"{day}_{cycle:02d}_f{lead:03d}",
                        gfs_url(day.isoformat(), cycle, lead, bbox),
                        {"run_date": day.isoformat(), "cycle_utc": cycle, "lead_hours": lead, "bbox": bbox})
                    self.transform(manifest)
                    completed += 1
        if not completed:
            raise ValueError("No GFS lead available")

    def ecmwf(self):
        """ECMWF IFS 0.25° forecast (Open Data, CC-BY-4.0, no registration).

        Each lead's file is global and carries dozens of variables. The index
        (.index, one JSON per line) gives each message's offset/size; only the
        configured variables are downloaded by byte range. ECMWF keeps only ~12 runs
        (2–3 days): what is not collected now cannot be fetched later here.
        """
        settings = self.config["ecmwf"]
        now = datetime.now(timezone.utc)
        discovery = json.loads((ROOT / "docs/inventory/weather_discovery.json").read_text(encoding="utf-8"))
        west, south, east, north = discovery["basins"]["bbox"]
        completed = 0
        for offset in range(settings["lookback_days"] + 1):
            day = now.date() - timedelta(days=offset)
            for cycle in settings["cycles"]:
                if datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=cycle) > now:
                    continue
                folder = f"https://data.ecmwf.int/forecasts/{day:%Y%m%d}/{cycle:02d}z/ifs/0p25/oper/"
                for lead in settings["leads"]:
                    stem = f"{day:%Y%m%d}{cycle:02d}0000-{lead}h-oper-fc"
                    try:
                        with open_http(folder + stem + ".index", timeout=60) as response:
                            entries = [json.loads(line) for line in response.read().decode().splitlines() if line.strip()]
                    except HTTPError as exc:
                        if exc.code == 404:
                            # Not published yet (or already expired): not a pipeline error.
                            continue
                        raise
                    chosen = [e for e in entries if e.get("param") in settings["params"] and e.get("levtype") == "sfc"]
                    missing = set(settings["params"]) - {e["param"] for e in chosen}
                    if missing:
                        self.log.warning("ECMWF %s missing variables %s", stem, sorted(missing))
                    if not chosen:
                        continue
                    ranges = sorted((int(e["_offset"]), int(e["_length"])) for e in chosen)
                    # The #params fragment makes the identity depend on the chosen variables
                    # (urllib does not send the fragment to the server).
                    url = folder + stem + ".grib2#params=" + ",".join(sorted(settings["params"]))
                    manifest = self.obtain("ecmwf", "ecmwf_ifs_0p25", f"{day}_{cycle:02d}z_f{lead:03d}", url,
                                           {"run_date": day.isoformat(), "cycle_utc": cycle, "lead_hours": lead,
                                            "params": sorted(settings["params"]), "license": "CC-BY-4.0 ECMWF"},
                                           100_000_000, ranges=ranges)
                    self.transform(manifest)
                    completed += 1
        if not completed:
            raise ValueError("No ECMWF lead available")

    def inmet(self):
        """The yearly ZIP is checked daily; GET and processing only when needed."""
        urls = listing("https://portal.inmet.gov.br/dadoshistoricos")
        annual = [u for u in urls if re.search(r"/20\d{2}\.zip$", u)]
        if not annual:
            raise ValueError("Nenhum pacote INMET anunciado")
        url = max(annual)
        year = re.search(r"(20\d{2})\.zip$", url).group(1)
        self.transform(self.obtain("inmet", "automatic_stations_annual", year, url,
            {"role": "station_observations"}, self.config["inmet"]["max_file_mb"] * 1_000_000))

    def fetch_load(self, kind, area, start, end, resource_id, role):
        """One load-API call; returns the Bronze manifest and the JSON list received."""
        url = LOAD_API.format(kind=kind) + urlencode(
            {"dat_inicio": start.isoformat(), "dat_fim": end.isoformat(), "cod_areacarga": area})
        context = {"api": "apicarga", "kind": kind, "area": area, "start": start.isoformat(),
                   "end": end.isoformat(), "role": role}
        manifest = self.obtain("ons", "carga-energia-" + kind, resource_id, url, context, 30_000_000, head=False)
        rows = parse_load_json(resolve_data_path(manifest["path"]))
        if not isinstance(rows, list):
            raise ValueError(f"API de carga devolveu {type(rows).__name__}, esperado lista")
        return manifest, rows

    def ons_load(self, kind):
        """Scheduled load (ONS forecast) and verified load (actual, revised) per area.

        dat_referencia is the Brazilian operating date, so 'today' here uses UTC-3
        (Brasília, no daylight saving since 2019), not the UTC date.
        """
        settings = self.config["ons_load"]
        today = datetime.now(timezone(timedelta(hours=-3))).date()
        if kind == "programada":
            days = [today + timedelta(days=o) for o in settings["programada_offsets"]]
            areas = settings["programada_areas"]
        else:
            # Verified load is republished over the following days; the window captures those revisions.
            days = [today - timedelta(days=o) for o in range(1, settings["verificada_lookback_days"] + 1)]
            areas = settings["verificada_areas"]
        for area in areas:
            for day in days:
                try:
                    manifest, rows = self.fetch_load(kind, area, day, day, f"{kind}_{area}_{day}", "daily")
                    if not rows:
                        # Publication edge: tomorrow's schedule and yesterday's verified load may not exist yet.
                        edge = day > today if kind == "programada" else day >= today - timedelta(days=1)
                        if edge:
                            self.log.info("Not published yet: load %s %s %s", kind, area, day)
                            continue
                        raise ValueError(f"Empty load API outside the publication edge: {kind} {area} {day}")
                    self.transform(manifest)
                except Exception as exc:
                    self.error(f"ons_load:{kind}:{area}:{day}", exc)

    def ccee(self):
        """CCEE spot prices (CKAN catalog). Bronze only until the real schema is observed.

        On 2026-11-10 CCEE's firewall returned 403 to this machine's egress IP
        (even on the home page). There is no workaround here: access is up to the network/CCEE.
        """
        settings = self.config["ccee"]
        today = datetime.now(timezone.utc).date()
        for name in settings["datasets"]:
            try:
                try:
                    payload = json_get(settings["catalog_url"] + "package_show?id=" + name)
                except Exception as exc:
                    if "403" in str(exc):
                        raise PermissionError("CCEE recusou o acesso (HTTP 403, firewall). Teste em outra rede "
                                              "or ask CCEE for access; the pipeline does not bypass blocks.") from exc
                    raise
                if not payload.get("success"):
                    raise ValueError("Falha CKAN CCEE")
                atomic_json(self.root / "catalog/pipeline" / self.run_id / ("ccee_" + name + ".json"), payload)
                selected = select_period(payload["result"]["resources"], today - timedelta(days=settings["lookback_days"]),
                                         today + timedelta(days=1), formats=settings["formats"])
                if not selected:
                    raise ValueError(f"Nenhum recurso recente {settings['formats']} em {name}")
                for item in selected:
                    manifest = self.obtain("ccee", name, item["id"], item["url"], item, settings["max_file_mb"] * 1_000_000)
                    self.report.setdefault("bronze_only", []).append(
                        {"source": "ccee", "dataset": name, "sha256": manifest["sha256"],
                         "reason": "Silver pending: CCEE schema not yet observed on this machine"})
            except Exception as exc:
                self.error("ccee:" + name, exc)

    def offline(self):
        """Rebuild Silver from the existing Bronze without using the network."""
        unique = {}
        for path in (self.root / "bronze").rglob("*.manifest.json"):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            supported = (manifest["source"] == "ons" and manifest["dataset"] in self.contracts and
                         manifest.get("context", {}).get("format", "").upper() in {"CSV", "PARQUET"})
            supported |= manifest["dataset"] in {"merge_daily", "gfs_0p25", "ecmwf_ifs_0p25", "automatic_stations_annual"}
            if manifest["dataset"] in LOAD_DATASETS:
                # Empty API responses stay in Bronze as evidence but produce no Silver.
                supported = resolve_data_path(manifest["path"]).exists() and manifest["bytes"] > 16
            if supported:
                key = (manifest["source"], manifest["dataset"], manifest["resource_id"], manifest["sha256"])
                if key not in unique or manifest["ingested_at"] < unique[key]["ingested_at"]:
                    unique[key] = manifest
        # If both formats exist, Parquet is the preferred publication for the slot.
        for manifest in sorted(unique.values(), key=lambda m: m.get("context", {}).get("format") == "PARQUET"):
            try:
                self.transform(manifest)
            except Exception as exc:
                self.error(manifest["dataset"], exc)

    def publish_current(self):
        """Rewrite the index of current snapshots from SQLite (the source of truth)."""
        pointers = [json.loads(row[0]) for row in self.state.execute("SELECT snapshot FROM snapshots ORDER BY identity")]
        atomic_json(self.root / "silver/current.json", {"updated_at": utcnow(), "snapshots": pointers,
                     "note": "Use only .valid.parquet files of the listed snapshots; history globs mix revisions. "
                             "Load (API): daily and monthly windows may overlap; deduplicate by "
                             "(cod_areacarga, din_referenciautc) mantendo o maior source_updated_at_utc/_available_at_utc."})

    def finish(self):
        """Publish an index of current snapshots and an immutable report per run."""
        self.publish_current()
        self.report.update(completed_at=utcnow(), status="partial" if self.report["errors"] else "success")
        atomic_json(self.root / "runs" / (self.run_id + ".json"), self.report)
        atomic_json(self.root / "runs/latest.json", self.report)
        return int(bool(self.report["errors"]))


def main():
    """Single entry point used from the terminal and by Task Scheduler."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--force", action="store_true", help="Ignores cadence but keeps the content cache")
    parser.add_argument("--tasks", default="ons,ons_load,merge,gfs,ecmwf,inmet,ccee")
    parser.add_argument("--no-gold", action="store_true", help="Does not update the Gold layer/views at the end")
    args = parser.parse_args()
    config = json.loads((ROOT / "configs/pipeline.json").read_text(encoding="utf-8"))
    contracts = json.loads((ROOT / "configs/ons_contracts.json").read_text(encoding="utf-8"))
    folder = DATA_DIR / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(folder / "pipeline.log", encoding="utf-8")])
    names = args.tasks.split(",")
    unknown = set(names) - {"ons", "ons_load", "merge", "gfs", "ecmwf", "inmet", "ccee"}
    if unknown:
        raise SystemExit(f"Tarefa desconhecida: {sorted(unknown)}")
    try:
        with single_run(DATA_DIR / "pipeline.lock"):
            pipeline = Pipeline(DATA_DIR, config, contracts, args.force)
            try:
                if args.offline:
                    pipeline.offline()
                else:
                    for name in names:
                        settings = config[name]
                        if not settings["enabled"]:
                            continue
                        if name == "ons_load":
                            # Forecasts change during the day; actuals come out ~once a day and are revised.
                            pipeline.task("ons_load_programada", settings["programada_interval_minutes"],
                                          lambda: pipeline.ons_load("programada"))
                            pipeline.task("ons_load_verificada", settings["verificada_interval_minutes"],
                                          lambda: pipeline.ons_load("verificada"))
                            continue
                        pipeline.task(name, settings["interval_minutes"], getattr(pipeline, name))
                        if name == "ons":
                            pipeline.task("ons_hourly_hydro", settings["hourly_hydro_interval_minutes"], lambda: pipeline.ons(True))
            except Exception as exc:
                # An unexpected error still produces a "partial" report instead of vanishing without a trace.
                pipeline.error("pipeline", exc)
            if pipeline.report["snapshots"] and not args.no_gold:
                # New Silver arrived: update basin means and views. A failure here never deletes Silver.
                try:
                    import gold
                    pipeline.publish_current()
                    pipeline.report["gold"] = gold.refresh(log=pipeline.log.info)
                except Exception as exc:
                    pipeline.error("gold", exc)
            try:
                return pipeline.finish()
            finally:
                pipeline.close()
    except LockBusy as exc:
        # Task Scheduler fires every 15 min; a long collection in progress is not a failure.
        logging.getLogger("pipeline").info("%s; another run is in progress, nothing to do.", exc)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
