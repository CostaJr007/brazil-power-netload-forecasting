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
    """Outra execução já segura a trava; não é falha da coleta."""


@contextmanager
def single_run(path):
    """Trava de processo liberada pelo sistema operacional mesmo após encerramento."""
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
    """Período coberto pelo nome do arquivo (ano, ano_mês ou ano_mês_dia); None se não houver data."""
    # Também reconhece 19xx: um arquivo de 1999 não pode ser confundido com cadastro sem data.
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
    """Seleciona arquivos cujo período intersecta [start, end]; cadastros sem data são opcionais."""
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
        # URL é identidade de transferência; ID do recurso permanece no contexto.
        chosen[url] = resource
    return sorted(chosen.values(), key=lambda r: r["url"])


def select_recent(resources, today, days):
    """Janela diária: últimos dias, incluindo viradas de mês/ano e programação D+1."""
    return select_period(resources, today - timedelta(days=days), today + timedelta(days=1))


class Pipeline:
    """Estado operacional e processamento; SQLite não é uma fila distribuída."""

    def __init__(self, root, config, contracts, force=False):
        self.root, self.config, self.contracts, self.force = Path(root), config, contracts, force
        self.store = Store(root)
        self.state = sqlite3.connect(self.root / "pipeline.sqlite", timeout=30)
        self.state.execute("CREATE TABLE IF NOT EXISTS tasks (name TEXT PRIMARY KEY, last_success TEXT)")
        self.state.execute("CREATE TABLE IF NOT EXISTS http (url TEXT PRIMARY KEY, fingerprint TEXT, manifest TEXT)")
        self.state.execute("CREATE TABLE IF NOT EXISTS snapshots (identity TEXT PRIMARY KEY, manifest TEXT, snapshot TEXT)")
        self.state.commit()
        # Mudar contrato, limite de qualidade ou código Silver produz outra versão de transformação.
        # Frequências/notas da configuração NÃO entram: mudá-las não deve reprocessar a Silver.
        # Quebras de linha normalizadas: CRLF (Windows) e LF geram a mesma versão.
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
        """Último sucesso controla a cadência; erro não adia a nova tentativa."""
        row = self.state.execute("SELECT last_success FROM tasks WHERE name=?", (name,)).fetchone()
        # Folga de meio tick evita pular uma coleta por poucos segundos de diferença
        # entre o término da execução anterior e o disparo de um agendador de 15 min.
        threshold = minutes - min(self.config["scheduler_minutes"] / 2, minutes / 2)
        return self.force or row is None or datetime.now(timezone.utc) - datetime.fromisoformat(row[0]) >= timedelta(minutes=threshold)

    def task(self, name, minutes, function):
        """Uma fonte pode falhar sem impedir as demais; o status global será partial."""
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
        """Usa o estado persistido ou procura uma aquisição anterior na Bronze."""
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
        # A comparação deve ser com a aquisição MAIS RECENTE: comparar com a mais antiga
        # faria baixar de novo um arquivo que já mudou e foi coletado depois.
        item = max(candidates, key=lambda m: m["ingested_at"])
        return self.fingerprint(item.get("headers", {})), item

    @staticmethod
    def fingerprint(headers):
        """ETag/Last-Modified são validadores de alteração, não datas dos registros."""
        h = {k.lower(): str(v) for k, v in headers.items()}
        if not (h.get("etag") or h.get("last-modified")):
            return None
        return json.dumps([h.get("etag"), h.get("last-modified"), h.get("content-length")])

    def obtain(self, source, dataset, resource_id, url, context=None, limit=150_000_000, head=True, ranges=None):
        """Faz HEAD antes do GET para não baixar novamente arquivos sem alteração.

        APIs dinâmicas (head=False) não têm validador estável: sempre GET, e o
        hash do conteúdo decide se houve revisão.
        """
        old_fp, previous = self.previous_manifest(url)
        current_fp = None
        if head:
            try:
                with urlopen(Request(url, method="HEAD", headers={"User-Agent": "EnergyDataStudy/0.2"}), timeout=30) as response:
                    current_fp = self.fingerprint(dict(response.headers.items()))
            except Exception as exc:
                self.log.warning("HEAD indisponível; tentando GET: %s (%s)", url, exc)
        if current_fp and current_fp == old_fp and previous and digest_file(resolve_data_path(previous["path"])) == previous["sha256"]:
            manifest = previous
            self.log.info("Sem alteração: %s", dataset)
        else:
            manifest = self.store.fetch(source, dataset, resource_id, url, limit, context=context, ranges=ranges)
            # Se os bytes são iguais, conserva a primeira disponibilidade comprovada.
            if previous and previous["sha256"] == manifest["sha256"]:
                manifest = {**manifest, "ingested_at": previous["ingested_at"]}
        with self.state:
            self.state.execute("INSERT OR REPLACE INTO http VALUES (?,?,?)",
                               (url, current_fp or self.fingerprint(manifest.get("headers", {})), json.dumps(manifest)))
        return manifest

    def transform(self, manifest):
        """Publica só snapshots que passam o contrato; último bom continua disponível."""
        dataset = manifest["dataset"]
        contract = self.contracts.get(dataset) or self.config.get("ons_load", {}).get("contracts", {}).get(dataset, {})
        discovery = json.loads((ROOT / "docs/inventory/weather_discovery.json").read_text(encoding="utf-8"))
        bbox = discovery["basins"]["bbox"]
        # Manifestos guardam caminho absoluto; se a pasta de dados mudou de disco, reencontra o arquivo.
        # (Feito aqui, e não em silver.py, porque o código de silver.py define a versão da Silver.)
        resolved = str(resolve_data_path(manifest["path"]))
        if resolved != manifest["path"]:
            manifest = {**manifest, "path": resolved}
        snapshot = build_silver(self.root, manifest, contract, self.version, bbox, self.config["max_invalid_fraction"])
        summary = {"source": manifest["source"], "dataset": dataset, "status": snapshot["status"],
                   "valid_rows": snapshot["valid_rows"], "rejected_rows": snapshot["rejected_rows"]}
        self.report["snapshots"].append(summary)
        if snapshot["status"] != "published":
            raise ValueError(f"Qualidade reprovada: {dataset}, fração inválida={snapshot['invalid_fraction']:.3%}")
        # CSV e Parquet do mesmo arquivo lógico ocupam o mesmo slot atual.
        # Na API de carga o caminho da URL é igual para todas as áreas/dias: o slot é o resource_id.
        by_file = manifest["source"] == "ons" and dataset not in LOAD_DATASETS
        slot = urlsplit(manifest["url"]).path.rsplit(".", 1)[0] if by_file else manifest["resource_id"]
        identity = f"{manifest['source']}|{dataset}|{slot}"
        with self.state:
            self.state.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?)",
                               (identity, json.dumps(manifest), json.dumps(snapshot)))
        self.log.info("Silver %s: %s válidas, %s rejeitadas", dataset, snapshot["valid_rows"], snapshot["rejected_rows"])

    def ons(self, only_hourly=False):
        """Consulta catálogo vivo e recursos recentes; inclui revisões dos últimos dias."""
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
                # Preserva a descoberta usada nesta execução, sem depender do catálogo de ontem.
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
        """Busca últimos dias, inclusive em virada de mês; ausência de D não é erro se D-1 existe."""
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
            raise ValueError("MERGE sem arquivo recente no intervalo de busca")

    def gfs(self):
        """Verifica ciclos realmente publicados; reconsulta para completar horizontes tardios."""
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
                    self.log.warning("Ciclo ainda indisponível: %s (%s)", base, exc)
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
            raise ValueError("Nenhum horizonte GFS disponível")

    def ecmwf(self):
        """Previsão ECMWF IFS 0,25° (Open Data, CC-BY-4.0, sem cadastro).

        O arquivo de cada horizonte é global e traz dezenas de variáveis. O índice
        (.index, JSON por linha) informa offset/tamanho de cada mensagem; baixamos só
        as variáveis configuradas por faixa de bytes. O ECMWF guarda apenas ~12 rodadas
        (2–3 dias): o que não for coletado agora não poderá ser buscado depois aqui.
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
                            # Ainda não publicado (ou já expirado): não é erro do pipeline.
                            continue
                        raise
                    chosen = [e for e in entries if e.get("param") in settings["params"] and e.get("levtype") == "sfc"]
                    missing = set(settings["params"]) - {e["param"] for e in chosen}
                    if missing:
                        self.log.warning("ECMWF %s sem variáveis %s", stem, sorted(missing))
                    if not chosen:
                        continue
                    ranges = sorted((int(e["_offset"]), int(e["_length"])) for e in chosen)
                    # O fragmento #params torna a identidade dependente das variáveis escolhidas
                    # (urllib não envia o fragmento ao servidor).
                    url = folder + stem + ".grib2#params=" + ",".join(sorted(settings["params"]))
                    manifest = self.obtain("ecmwf", "ecmwf_ifs_0p25", f"{day}_{cycle:02d}z_f{lead:03d}", url,
                                           {"run_date": day.isoformat(), "cycle_utc": cycle, "lead_hours": lead,
                                            "params": sorted(settings["params"]), "license": "CC-BY-4.0 ECMWF"},
                                           100_000_000, ranges=ranges)
                    self.transform(manifest)
                    completed += 1
        if not completed:
            raise ValueError("Nenhum horizonte ECMWF disponível")

    def inmet(self):
        """O ZIP anual é checado diariamente; GET e tratamento só se necessário."""
        urls = listing("https://portal.inmet.gov.br/dadoshistoricos")
        annual = [u for u in urls if re.search(r"/20\d{2}\.zip$", u)]
        if not annual:
            raise ValueError("Nenhum pacote INMET anunciado")
        url = max(annual)
        year = re.search(r"(20\d{2})\.zip$", url).group(1)
        self.transform(self.obtain("inmet", "automatic_stations_annual", year, url,
            {"role": "station_observations"}, self.config["inmet"]["max_file_mb"] * 1_000_000))

    def fetch_load(self, kind, area, start, end, resource_id, role):
        """Uma chamada da API de carga; devolve manifesto Bronze e a lista JSON recebida."""
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
        """Carga programada (previsão do ONS) e verificada (realizada, revisada) por área.

        dat_referencia é a data operativa brasileira; por isso o 'hoje' aqui usa UTC-3
        (Brasília sem horário de verão desde 2019), não a data UTC.
        """
        settings = self.config["ons_load"]
        today = datetime.now(timezone(timedelta(hours=-3))).date()
        if kind == "programada":
            days = [today + timedelta(days=o) for o in settings["programada_offsets"]]
            areas = settings["programada_areas"]
        else:
            # A verificada é republicada nos dias seguintes; a janela captura essas revisões.
            days = [today - timedelta(days=o) for o in range(1, settings["verificada_lookback_days"] + 1)]
            areas = settings["verificada_areas"]
        for area in areas:
            for day in days:
                try:
                    manifest, rows = self.fetch_load(kind, area, day, day, f"{kind}_{area}_{day}", "daily")
                    if not rows:
                        # Borda de publicação: programada de amanhã e verificada de ontem podem ainda não existir.
                        edge = day > today if kind == "programada" else day >= today - timedelta(days=1)
                        if edge:
                            self.log.info("Ainda não publicado: carga %s %s %s", kind, area, day)
                            continue
                        raise ValueError(f"API de carga vazia fora da borda de publicação: {kind} {area} {day}")
                    self.transform(manifest)
                except Exception as exc:
                    self.error(f"ons_load:{kind}:{area}:{day}", exc)

    def ccee(self):
        """PLD e preços da CCEE (catálogo CKAN). Só Bronze até o schema real ser observado.

        Em 10/11/2026 o firewall da CCEE devolveu 403 para o IP de saída desta máquina
        (inclusive na página inicial). Não há contorno aqui: liberar o acesso é com a rede/CCEE.
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
                                              "ou solicite liberação à CCEE; o pipeline não contorna bloqueios.") from exc
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
                         "reason": "Silver pendente: schema CCEE ainda não observado nesta máquina"})
            except Exception as exc:
                self.error("ccee:" + name, exc)

    def offline(self):
        """Reconstrói a Silver a partir da Bronze existente sem consultar a internet."""
        unique = {}
        for path in (self.root / "bronze").rglob("*.manifest.json"):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            supported = (manifest["source"] == "ons" and manifest["dataset"] in self.contracts and
                         manifest.get("context", {}).get("format", "").upper() in {"CSV", "PARQUET"})
            supported |= manifest["dataset"] in {"merge_daily", "gfs_0p25", "ecmwf_ifs_0p25", "automatic_stations_annual"}
            if manifest["dataset"] in LOAD_DATASETS:
                # Respostas vazias da API ficam na Bronze como evidência, mas não geram Silver.
                supported = resolve_data_path(manifest["path"]).exists() and manifest["bytes"] > 16
            if supported:
                key = (manifest["source"], manifest["dataset"], manifest["resource_id"], manifest["sha256"])
                if key not in unique or manifest["ingested_at"] < unique[key]["ingested_at"]:
                    unique[key] = manifest
        # Se existem ambos os formatos, o Parquet fica como publicação preferida do slot.
        for manifest in sorted(unique.values(), key=lambda m: m.get("context", {}).get("format") == "PARQUET"):
            try:
                self.transform(manifest)
            except Exception as exc:
                self.error(manifest["dataset"], exc)

    def publish_current(self):
        """Reescreve o índice de snapshots atuais a partir do SQLite (fonte da verdade)."""
        pointers = [json.loads(row[0]) for row in self.state.execute("SELECT snapshot FROM snapshots ORDER BY identity")]
        atomic_json(self.root / "silver/current.json", {"updated_at": utcnow(), "snapshots": pointers,
                     "note": "Use só arquivos .valid.parquet dos snapshots listados; globs de histórico misturam revisões. "
                             "Carga (API): janelas diárias e mensais podem se sobrepor; deduplicar por "
                             "(cod_areacarga, din_referenciautc) mantendo o maior source_updated_at_utc/_available_at_utc."})

    def finish(self):
        """Publica um índice de snapshots atuais e um relatório imutável por execução."""
        self.publish_current()
        self.report.update(completed_at=utcnow(), status="partial" if self.report["errors"] else "success")
        atomic_json(self.root / "runs" / (self.run_id + ".json"), self.report)
        atomic_json(self.root / "runs/latest.json", self.report)
        return int(bool(self.report["errors"]))


def main():
    """Entrada única usada no terminal e pelo Agendador de Tarefas."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--force", action="store_true", help="Ignora cadência, mas mantém cache por conteúdo")
    parser.add_argument("--tasks", default="ons,ons_load,merge,gfs,ecmwf,inmet,ccee")
    parser.add_argument("--no-gold", action="store_true", help="Não atualiza a camada Gold/views ao final")
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
                            # Previsão muda ao longo do dia; realizado sai ~1x/dia e é revisado.
                            pipeline.task("ons_load_programada", settings["programada_interval_minutes"],
                                          lambda: pipeline.ons_load("programada"))
                            pipeline.task("ons_load_verificada", settings["verificada_interval_minutes"],
                                          lambda: pipeline.ons_load("verificada"))
                            continue
                        pipeline.task(name, settings["interval_minutes"], getattr(pipeline, name))
                        if name == "ons":
                            pipeline.task("ons_hourly_hydro", settings["hourly_hydro_interval_minutes"], lambda: pipeline.ons(True))
            except Exception as exc:
                # Erro inesperado ainda gera relatório "partial" em vez de sumir sem rastro.
                pipeline.error("pipeline", exc)
            if pipeline.report["snapshots"] and not args.no_gold:
                # Houve Silver nova: atualiza médias por bacia e views. Falha aqui não apaga a Silver.
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
        # O Agendador dispara a cada 15 min; uma coleta longa em andamento não é falha.
        logging.getLogger("pipeline").info("%s; outra execução está em andamento, nada a fazer.", exc)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
