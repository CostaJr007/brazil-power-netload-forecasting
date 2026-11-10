"""Baixa um primeiro lote meteorológico e documenta seu conteúdo, sem modelagem.

Pré-requisito: executar discover_weather.py. Por padrão: sete dias MERGE,
três horizontes GFS e o ZIP anual atual do INMET. Os bytes vão para a Bronze.
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

# ecCodes lê as mensagens GRIB; NumPy verifica os valores sem alterar o arquivo.
import eccodes
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import is_valid_reason

# Reutilizamos auditoria, escrita e geração de URL já existentes.
# Scripts desta subpasta reutilizam os módulos de scripts/ (acquire, pipeline...).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from acquire import DATA_DIR, ROOT, Store, atomic_json, gfs_url, utcnow
from discover_weather import listing


def grib_inventory(path):
    """Lê mensagens GRIB e registra variável, unidade, rodada e acumulação."""
    messages = []
    # Um GRIB pode conter várias mensagens com níveis e intervalos diferentes.
    with Path(path).open("rb") as stream:
        while True:
            handle = eccodes.codes_grib_new_from_file(stream)
            if handle is None:
                break
            try:
                record = {}
                # startStep/endStep são importantes: APCP em f024 não significa
                # automaticamente chuva acumulada desde o início da rodada.
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
                # missingValue é sentinela; um número finito pode ainda representar falta.
                missing = eccodes.codes_get(handle, "missingValue")
                good = np.isfinite(values) & (values != missing)
                record["valid_values"] = int(good.sum())
                record["min_value"] = float(values[good].min()) if good.any() else None
                record["max_value"] = float(values[good].max()) if good.any() else None
                lats = eccodes.codes_get_array(handle, "latitudes")
                lons = eccodes.codes_get_array(handle, "longitudes")
                # Padronização só no relatório: preservamos os bytes e as coordenadas GRIB.
                signed_lons = (lons + 180) % 360 - 180
                record["bbox_wgs84"] = [float(signed_lons.min()), float(lats.min()),
                                         float(signed_lons.max()), float(lats.max())]
                messages.append(record)
            finally:
                # A mensagem ocupa memória nativa e precisa ser liberada a cada iteração.
                eccodes.codes_release(handle)
    if not messages:
        raise ValueError("Arquivo sem mensagens GRIB decodificáveis")
    return messages


def inspect_basins(discovery):
    """Publica apenas metadados espaciais e motivos de invalidez da origem."""
    frame = gpd.read_file("zip://" + discovery["basins"]["access_copy"].replace("\\", "/"))
    frame = frame.to_crs("EPSG:4326")
    frame["source_geometry_valid"] = frame.geometry.is_valid
    frame["source_geometry_reason"] = frame.geometry.map(is_valid_reason)
    folder = DATA_DIR / "geography"
    # GeoParquet é um produto de cadastro/inspeção; não corrige a geometria original.
    frame.to_parquet(folder / "ons_basins_inspected.parquet", index=False)
    fields = ["ID", "Nome_Bacia", "source_geometry_valid", "source_geometry_reason"]
    details = frame[fields].to_dict("records")
    atomic_json(folder / "ons_basins_quality.json", details)
    return frame, details


def station_inventory(manifest, basins):
    """Lê metadados de estações dentro do ZIP INMET e mantém referência ao membro."""
    stations, errors = [], []
    with ZipFile(manifest["path"]) as archive:
        members = [m for m in archive.namelist() if m.lower().endswith(".csv")]
        for member in members:
            try:
                with archive.open(member) as stream:
                    # Os oito primeiros registros contêm cadastro, não observações horárias.
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
        # Lemos um membro completo para verificar referência e sentinelas como amostra.
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
                           "scope": "Apenas um membro; não certifica cobertura de todas as estações."}
    if not stations:
        raise ValueError("Nenhum cadastro de estação foi lido; verificar encoding/header INMET")
    table = pd.DataFrame(stations)
    # Interseção apenas com geometrias válidas; não reparamos as seis inválidas.
    points = gpd.GeoDataFrame(table.drop(columns="metadata"),
                             geometry=gpd.points_from_xy(table.longitude, table.latitude), crs="EPSG:4326")
    valid = basins.loc[basins.source_geometry_valid, ["ID", "Nome_Bacia", "geometry"]]
    matches = gpd.sjoin(points, valid, how="left", predicate="intersects")
    matches.drop(columns="geometry").to_parquet(DATA_DIR / "geography/inmet_stations_basin_candidates.parquet", index=False)
    atomic_json(DATA_DIR / "geography/inmet_station_inventory.json", {"stations": stations, "errors": errors})
    return {"csv_members": len(members), "stations_read": len(stations), "metadata_errors": errors,
            "stations_intersecting_valid_basins": int(matches.loc[matches.ID.notna(), "member"].nunique()),
            "spatial_limit": "Junção candidata só com bacias válidas; ausência de vínculo não significa estação fora de todas as bacias.",
            "sample_observations": example}


def main():
    """Organiza o lote, preserva originais e publica evidências após cada arquivo."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7, help="Quantidade de arquivos diários MERGE")
    parser.add_argument("--skip-inmet", action="store_true", help="Omite ZIP anual na repetição")
    args = parser.parse_args()
    if not 1 <= args.days <= 31:
        raise ValueError("Use de 1 a 31 dias neste lote inicial")
    discovery = json.loads((ROOT / "docs/inventory/weather_discovery.json").read_text(encoding="utf-8"))
    basins, quality = inspect_basins(discovery)
    west, south, east, north = discovery["basins"]["bbox"]
    # Arredondamos para fora e acrescentamos margem de grade: não é recorte do polígono.
    bbox = [math.floor(west * 4) / 4 - .25, math.floor(south * 4) / 4 - .25,
            math.ceil(east * 4) / 4 + .25, math.ceil(north * 4) / 4 + .25]
    report = {"started_at": utcnow(), "collection": "initial_weather_acquisition",
              "basin_quality": quality, "forecast_bbox": bbox, "files": [], "errors": []}
    store = Store(DATA_DIR)
    report_path = ROOT / "docs/inventory/weather_acquisition.json"

    def collect(source, dataset, resource_id, url, context, kind="grib", limit=100_000_000):
        """Baixa via Store e separa sucesso HTTP de sucesso de decodificação."""
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
                     "note": "Acumulação será interpretada com CTL e documentação, não só pelo nome."})
        if daily:
            # CTL e manual documentam grade e convenção de acumulação da chuva.
            ctl = daily[-1].replace(".grib2", ".ctl")
            collect("inpe", "merge_documentation", "latest_ctl", ctl, {"role": "product_metadata"}, "text")
        manuals = [u for u in discovery["sources"]["merge_root"]["links"] if u.endswith("MERGE_READ-ME.pdf")]
        for url in manuals:
            collect("inpe", "merge_documentation", "readme", url, {"role": "documentation"}, "binary")

        # Confirmamos disponibilidade de cada horizonte em um diretório real da NOAA.
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
            raise ValueError("Nenhuma rodada GFS 00 UTC com os três horizontes foi confirmada")
        for lead in [24, 48, 72]:
            collect("noaa", "gfs_0p25", f"{chosen}_00_f{lead:03d}", gfs_url(chosen, 0, lead, bbox),
                    {"role": "forecast", "run_date": chosen, "cycle_utc": 0,
                     "lead_hours": lead, "requested_bbox": bbox,
                     "note": "Grade retangular; startStep/endStep específicos por variável."})
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
