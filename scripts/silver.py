"""Tratamento Bronze -> Silver, mantendo a origem e separando rejeições.

Os comentários explicam as regras de negócio. Arquivos da Bronze nunca são editados.
"""
import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import ZipFile

import eccodes
import geopandas as gpd
import numpy as np
import polars as pl

from acquire import atomic_json, utcnow


def snake(value):
    """Remove acentos e pontuação de nomes de colunas, sem alterar os dados brutos."""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def lineage(frame, manifest):
    """Anexa proveniência; disponibilidade é a coleta comprovada, não uma data presumida."""
    seen = datetime.fromisoformat(manifest["ingested_at"])
    return frame.with_columns(
        pl.lit(manifest["source"]).alias("_source"),
        pl.lit(manifest["dataset"]).alias("_dataset"),
        pl.lit(manifest["resource_id"]).alias("_resource_id"),
        pl.lit(manifest["sha256"]).alias("_source_sha256"),
        pl.lit(seen).cast(pl.Datetime("us", "UTC")).alias("_available_at_utc"))


def split_quality(frame, rules):
    """Regras retornam máscaras de erro; nunca substituímos valores inválidos por zero."""
    reasons = [pl.when(mask.fill_null(False)).then(pl.lit(name)).otherwise(pl.lit(None))
               for name, mask in rules]
    if reasons:
        frame = frame.with_columns(pl.concat_list(reasons).list.drop_nulls().alias("_quality_errors"))
    else:
        frame = frame.with_columns(pl.lit([], dtype=pl.List(pl.String)).alias("_quality_errors"))
    bad = pl.col("_quality_errors").list.len() > 0
    return frame.filter(~bad), frame.filter(bad)


def ons_frame(path, manifest, contract):
    """Tipa ONS, normaliza chaves e valida conversões; mantém todas as colunas da origem."""
    fmt = manifest.get("context", {}).get("format", "PARQUET").upper()
    frame = pl.read_csv(path, separator=";", infer_schema=False) if fmt == "CSV" else pl.read_parquet(path)
    source_rows = frame.height
    required = contract.get("required", [])
    # "optional": colunas que a fonte só passou a publicar a partir de certa data
    # (arquivos antigos não as têm). Ausência delas não reprova o arquivo.
    missing = sorted(set(required) - set(frame.columns) - set(contract.get("optional", [])))
    if missing:
        raise ValueError(f"Schema incompatível, colunas ausentes: {missing}")
    # Só duplicatas exatamente iguais são removidas. Conflitos entre chaves ficam visíveis.
    frame = frame.unique(maintain_order=True)
    duplicate_rows = source_rows - frame.height
    rules, transforms = [], []
    for name, dtype in frame.schema.items():
        if name.startswith(("id_", "cod_")) or name == "ceg":
            transforms.append(pl.col(name).cast(pl.String).str.strip_chars().alias(name))
        elif dtype == pl.String:
            transforms.append(pl.col(name).str.strip_chars().alias(name))
    frame = frame.with_columns(transforms)
    # O contrato descreve campos numéricos observados no schema auditado.
    for name in contract.get("numeric", []):
        if name not in frame.columns:
            continue
        original = pl.col(name)
        text = original.cast(pl.String).str.replace_all(",", ".")
        value = text.cast(pl.Float64, strict=False)
        frame = frame.with_columns(((original.is_not_null()) & (text != "") & value.is_null()).alias("_bad_" + name),
                                   value.alias(name))
        rules.append(("invalid_numeric:" + name, pl.col("_bad_" + name)))
        rules.append(("nonfinite:" + name, pl.col(name).is_not_null() & ~pl.col(name).is_finite()))
    # Hora da fonte é preservada sem inventar UTC; o dicionário de cada fonte pode diferir.
    event = contract.get("event_column")
    if event and event in frame.columns:
        text = pl.col(event).cast(pl.String)
        parsed = pl.coalesce(text.str.to_datetime("%Y-%m-%d %H:%M:%S", strict=False),
                             text.str.to_datetime("%Y-%m-%d %H:%M:%S%.f", strict=False),
                             text.str.to_datetime("%Y-%m-%d", strict=False),
                             text.str.to_datetime("%Y%m%d", strict=False),
                             text.str.to_datetime("%d/%m/%Y", strict=False))
        frame = frame.with_columns(parsed.alias("_event_time_source"),
                                   pl.lit("unverified_source_timezone").alias("_timezone_status"))
        rules.append(("invalid_event_time", pl.col("_event_time_source").is_null()))
    if "id_subsistema" in frame.columns:
        frame = frame.with_columns(pl.col("id_subsistema").str.to_uppercase()
                                   .replace({"SE/CO": "SE"}).alias("id_subsistema"))
        rules.append(("unknown_subsystem", ~pl.col("id_subsistema").is_in(["SE", "S", "NE", "N", "SIN"])))
        frame = frame.with_columns((pl.col("id_subsistema") == "SIN").alias("_is_sin_aggregate"))
    # ENA percentual da MLT pode superar 100: não aplicamos o limite de reservatório a ela.
    warnings = []
    for name in ["ear_verif_subsistema_percentual", "ear_verif_bacia_percentual",
                 "ear_verif_ree_percentual", "ear_reservatorio_percentual"]:
        if name in frame.columns:
            # A própria fonte tem valores acima de 100 (ex.: volume acima da referência).
            # Sinalizamos investigação sem truncar ou declarar que o dado é inválido.
            warnings.append(pl.when(~pl.col(name).is_between(0, 100)).then(
                pl.lit("outside_nominal_range:" + name)).otherwise(pl.lit(None)))
    frame = frame.with_columns((pl.concat_list(warnings).list.drop_nulls() if warnings else
                                pl.lit([], dtype=pl.List(pl.String))).alias("_quality_warnings"))
    # Após normalizar espaços/tipos, linhas antes distintas podem se tornar iguais.
    frame = frame.unique(maintain_order=True)
    duplicate_rows = source_rows - frame.height
    frame = lineage(frame, manifest)
    valid, rejected = split_quality(frame, rules)
    helpers = [n for n in frame.columns if n.startswith("_bad_")]
    maximum = frame["_event_time_source"].max() if "_event_time_source" in frame.columns else None
    return valid.drop(helpers), rejected.drop(helpers), {"input_rows": source_rows,
            "exact_duplicates_removed": duplicate_rows, "timezone": "source timezone not asserted",
            "warning_rows": frame.filter(pl.col("_quality_warnings").list.len() > 0).height,
            "max_event_time_source": str(maximum) if maximum else None,
            "new_columns": sorted(set(frame.columns) - set(contract.get("required", [])) - set(n for n in frame.columns if n.startswith("_")))}


LOAD_DATASETS = {"carga-energia-programada", "carga-energia-verificada"}


def parse_load_json(path):
    """Lê a resposta da API de carga tolerando um defeito conhecido da fonte.

    Em períodos antigos (ex.: 2018 a início de 2019) a API escreve campos sem valor
    como  "val_cargammgd": ,  — isso não é JSON válido. Só esse padrão (dois-pontos
    seguido direto de vírgula, } ou ]) vira null; nenhum valor é inventado e os
    bytes originais continuam intactos na Bronze.
    """
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(re.sub(r":\s*(?=[,}\]])", ": null", text))


def load_frame(path, manifest, contract):
    """Tipa a resposta JSON da API de carga do ONS (apicarga).

    O dicionário oficial declara din_referenciautc em UTC+0 e como FINAL do
    intervalo de meia hora; por isso o início é calculado subtraindo 30 minutos.
    Esta é a única fonte ONS do projeto com fuso horário declarado.
    """
    payload = parse_load_json(path)
    if not isinstance(payload, list):
        raise ValueError("Resposta da API de carga não é uma lista JSON")
    if not payload:
        raise ValueError("Resposta da API de carga vazia")
    # Todos os campos entram como texto; a conversão abaixo registra falhas.
    columns = sorted({key for row in payload for key in row})
    frame = pl.DataFrame([{k: (None if row.get(k) is None else str(row.get(k))) for k in columns} for row in payload],
                         schema={k: pl.String for k in columns})
    source_rows = frame.height
    missing = sorted(set(contract.get("required", [])) - set(frame.columns))
    if missing:
        raise ValueError(f"Schema incompatível, colunas ausentes: {missing}")
    frame = frame.unique(maintain_order=True)
    rules = []
    for name in [c for c in frame.columns if c.startswith("val_")]:
        value = pl.col(name).str.strip_chars().cast(pl.Float64, strict=False)
        frame = frame.with_columns((pl.col(name).is_not_null() & value.is_null()).alias("_bad_" + name), value.alias(name))
        rules.append(("invalid_numeric:" + name, pl.col("_bad_" + name)))
        rules.append(("nonfinite:" + name, pl.col(name).is_not_null() & ~pl.col(name).is_finite()))
    end = pl.col("din_referenciautc").str.to_datetime("%Y-%m-%dT%H:%M:%S%.fZ", strict=False, time_zone="UTC")
    frame = frame.with_columns(end.alias("interval_end_utc"),
                               (end - pl.duration(minutes=30)).alias("interval_start_utc"),
                               pl.col("cod_areacarga").str.strip_chars().alias("cod_areacarga"),
                               pl.lit("declared_utc_by_source_dictionary").alias("_timezone_status"))
    if "din_atualizacao" in frame.columns:
        # Data de atualização da fonte: a carga verificada é revisada depois do dia.
        frame = frame.with_columns(pl.col("din_atualizacao").str.to_datetime(
            "%Y-%m-%dT%H:%M:%S%.fZ", strict=False, time_zone="UTC").alias("source_updated_at_utc"))
    rules.append(("invalid_interval_end", pl.col("interval_end_utc").is_null()))
    # Mesma área e mesmo intervalo duas vezes na mesma resposta é conflito, não revisão.
    rules.append(("duplicate_key", pl.struct("cod_areacarga", "din_referenciautc").is_duplicated()))
    # Carga global zero é fisicamente implausível para uma área inteira. A fonte publica
    # assim (ex.: área SIN em 10/11/2026); sinalizamos sem apagar nem corrigir.
    total = next((c for c in ("val_cargaglobal", "val_cargaglobalprogramada") if c in frame.columns), None)
    warning = (pl.when(pl.col(total) == 0).then(pl.lit(["zero_total_load"])).otherwise(pl.lit([], dtype=pl.List(pl.String)))
               if total else pl.lit([], dtype=pl.List(pl.String)))
    frame = lineage(frame, manifest).with_columns(warning.alias("_quality_warnings"))
    valid, rejected = split_quality(frame, rules)
    helpers = [n for n in frame.columns if n.startswith("_bad_")]
    maximum = frame["interval_end_utc"].max()
    return valid.drop(helpers), rejected.drop(helpers), {
        "input_rows": source_rows, "exact_duplicates_removed": source_rows - frame.height,
        "timezone": "UTC declared by source dictionary; din_referenciautc marks interval end",
        "warning_rows": frame.filter(pl.col("_quality_warnings").list.len() > 0).height,
        "max_interval_end_utc": str(maximum) if maximum else None}


def grib_frames(path, manifest, bbox):
    """Converte mensagens meteorológicas em tabela longa, preservando rodada e intervalo."""
    parts = []
    with Path(path).open("rb") as stream:
        while True:
            handle = eccodes.codes_grib_new_from_file(stream)
            if handle is None:
                break
            try:
                def get(key, default=None):
                    try:
                        return eccodes.codes_get(handle, key)
                    except eccodes.CodesInternalError:
                        return default
                name, unit = get("shortName"), get("units")
                values = eccodes.codes_get_values(handle)
                lat = eccodes.codes_get_array(handle, "latitudes")
                lon = (eccodes.codes_get_array(handle, "longitudes") + 180) % 360 - 180
                west, south, east, north = bbox
                mask = (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)
                values = values[mask].copy()
                values[(~np.isfinite(values)) | (values == get("missingValue"))] = np.nan
                # dataDate/dataTime descrevem o GRIB. Em MERGE não são uma rodada de previsão.
                reference = datetime.strptime(f"{get('dataDate'):08d}{get('dataTime'):04d}", "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                valid = datetime.strptime(f"{get('validityDate'):08d}{get('validityTime'):04d}", "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                merge = manifest["dataset"] == "merge_daily"
                variable = name
                if merge:
                    # Interpretação vem do CTL, e não do rótulo genérico do ecCodes.
                    codes = (get("discipline"), get("parameterCategory"), get("parameterNumber"))
                    mapping = {(0, 15, 5): ("precipitation_mm", "mm"), (0, 3, 1): ("station_count", "count")}
                    if codes not in mapping:
                        raise ValueError(f"Campo MERGE não documentado no contrato: {codes}")
                    variable, unit = mapping[codes]
                elif name in {"tp", "ro"} and unit == "m":
                    # ECMWF: chuva total e escoamento em METROS de água acumulados desde o início
                    # da rodada. 1 m = 1000 mm. (No GFS a chuva vem em kg/m², que já equivale a mm.)
                    variable = "precipitation_mm" if name == "tp" else "runoff_mm"
                    unit, values = "mm", values * 1000
                elif name == "ssrd":
                    # Radiação solar descendente ACUMULADA (energia por área), não fluxo instantâneo.
                    variable, unit = "solar_radiation_accum_j_m2", "J m**-2"
                elif unit == "K":
                    variable, unit, values = "temperature_c", "degC", values - 273.15
                elif unit == "kg m**-2":
                    variable, unit = "precipitation_mm", "mm"
                elif name in {"u", "10u", "100u"}:
                    variable, unit = "wind_u", "m/s"
                elif name in {"v", "10v", "100v"}:
                    variable, unit = "wind_v", "m/s"
                # Os intervalos GFS vêm dos passos em horas. Não atribuimos janela diária ao MERGE.
                start, end = get("startStep", 0), get("endStep", 0)
                if not merge and get("stepUnits") != 1:
                    raise ValueError("Unidade de passo GRIB ainda não suportada; esperado horas")
                part = pl.DataFrame({"latitude": lat[mask], "longitude": lon[mask], "value": values}, nan_to_null=True)
                part = part.with_columns(pl.lit(variable).alias("variable"), pl.lit(name).alias("source_variable"),
                    pl.lit(unit).alias("unit"), pl.lit(get("units")).alias("source_unit"),
                    pl.lit(get("typeOfLevel")).alias("level_type"), pl.lit(float(get("level", 0))).alias("level"),
                    pl.lit(valid).alias("valid_time_utc"),
                    pl.lit(None if merge else reference, dtype=pl.Datetime("us", "UTC")).alias("run_time_utc"),
                    pl.lit(None if merge else reference + timedelta(hours=start), dtype=pl.Datetime("us", "UTC")).alias("interval_start_utc"),
                    pl.lit(None if merge else reference + timedelta(hours=end), dtype=pl.Datetime("us", "UTC")).alias("interval_end_utc"),
                    pl.lit(get("stepType")).alias("step_type"),
                    pl.lit("closure_unverified" if merge else "declared_grib_interval").alias("interval_status"))
                parts.append(part)
            finally:
                eccodes.codes_release(handle)
    if not parts:
        raise ValueError("GRIB sem mensagens")
    frame = lineage(pl.concat(parts, how="vertical_relaxed"), manifest)
    # Ausência é mantida como null e sinalizada. Não imputamos chuva/vento ausentes.
    frame = frame.with_columns(pl.col("value").is_null().alias("_is_missing"))
    rules = [("negative_precipitation", (pl.col("variable") == "precipitation_mm") & (pl.col("value") < 0)),
             ("negative_station_count", (pl.col("variable") == "station_count") & (pl.col("value") < 0))]
    valid, rejected = split_quality(frame, rules)
    return valid, rejected, {"input_rows": frame.height, "messages": len(parts), "bbox": bbox}


def inmet_frames(path, manifest):
    """Produz uma estação de cada vez para limitar memória durante o ZIP anual."""
    with ZipFile(path) as archive:
        for member in sorted(m for m in archive.namelist() if m.lower().endswith(".csv")):
            with archive.open(member) as raw:
                text = io.TextIOWrapper(raw, encoding="latin-1")
                metadata = {}
                for _ in range(8):
                    key, value = text.readline().strip().split(";", 1)
                    metadata[key.rstrip(":")] = value.strip(";")
                reader = csv.reader(text, delimiter=";")
                header = next(reader)
                names = [snake(n) or "_trailing_empty" for n in header]
                if len(names) != len(set(names)):
                    raise ValueError(f"Colunas duplicadas após normalização: {member}")
                rows = list(reader)
            # O schema explícito impede que colunas vazias sejam inferidas como Null.
            frame = pl.DataFrame(rows, schema={n: pl.String for n in names}, orient="row")
            if "_trailing_empty" in frame.columns:
                if frame["_trailing_empty"].str.len_chars().sum() != 0:
                    raise ValueError("Coluna sem nome contém dados")
                frame = frame.drop("_trailing_empty")
            datecol, hourcol = names[:2]
            # Até ~2019 o INMET publica "2018-01-01;00:00"; depois, "2022/01/01;0000 UTC".
            day = pl.col(datecol).str.replace_all("-", "/", literal=True)
            hour = pl.col(hourcol).str.replace(":", "", literal=True).str.extract(r"(\d{4})", 1)
            stamp = pl.concat_str([day, pl.lit(" "), hour])
            frame = frame.with_columns(stamp.str.to_datetime("%Y/%m/%d %H%M", strict=False).dt.replace_time_zone("UTC").alias("observed_at_utc"))
            rules = [("invalid_timestamp", pl.col("observed_at_utc").is_null())]
            numeric = [n for n in frame.columns if n not in {datecol, hourcol, "observed_at_utc"}]
            for name in numeric:
                original = pl.col(name).str.strip_chars()
                number = original.str.replace_all(",", ".").cast(pl.Float64, strict=False)
                frame = frame.with_columns((original.is_not_null() & (original != "") & number.is_null()).alias("_bad_" + name),
                                           pl.when(number == -9999).then(None).otherwise(number).alias(name))
                rules.append(("invalid_numeric:" + name, pl.col("_bad_" + name)))
                rules.append(("nonfinite:" + name, pl.col(name).is_not_null() & ~pl.col(name).is_finite()))
                if name.startswith("umidade"):
                    rules.append(("humidity_outside_0_100:" + name, ~pl.col(name).is_between(0, 100)))
            # Nomes/unidades comuns sem tratar radiação acumulada como fluxo instantâneo.
            mapping = {"precipitacao_total_horario_mm": "precipitation_mm",
                       "temperatura_do_ar_bulbo_seco_horaria_c": "air_temperature_c",
                       "vento_velocidade_horaria_m_s": "wind_speed_m_s"}
            rename = {k: v for k, v in mapping.items() if k in frame.columns}
            # O nome das duas primeiras colunas também muda entre anos (data_yyyy_mm_dd, hora_utc...).
            rename |= {datecol: "data", hourcol: "hora_utc"}
            frame = frame.with_columns(pl.lit(metadata.get("CODIGO (WMO)")).alias("station_id"),
                pl.lit(float(metadata["LATITUDE"].replace(",", "."))).alias("latitude"),
                pl.lit(float(metadata["LONGITUDE"].replace(",", "."))).alias("longitude"),
                pl.lit(member).alias("_zip_member"))
            frame = lineage(frame, manifest)
            valid, rejected = split_quality(frame, rules)
            helpers = [n for n in frame.columns if n.startswith("_bad_")]
            missing_cells = {mapping.get(n, n): frame[n].null_count() for n in numeric}
            # Missing não significa zero: a contagem fica no relatório de qualidade.
            yield snake(Path(member).stem), valid.drop(helpers).rename(rename), rejected.drop(helpers).rename(rename), {
                "input_rows": frame.height, "member": member, "missing_measurements": missing_cells,
                "max_observed_at_utc": str(frame["observed_at_utc"].max())}


def build_silver(root, manifest, contract, version, bbox, max_invalid=0.01):
    """Publica snapshot por hash e versão; nunca mistura revisões na mesma tabela."""
    dataset = manifest["dataset"]
    destination = Path(root) / "silver" / manifest["source"] / dataset / manifest["resource_id"] / version / manifest["sha256"]
    # O manifesto é o marcador de publicação: arquivos sem ele não estão prontos para consumo.
    success = destination / "snapshot.json"
    if success.exists():
        previous = json.loads(success.read_text(encoding="utf-8"))
        if previous.get("status") == "published" and all(Path(p).exists() for p in previous["files"]):
            return previous
    destination.mkdir(parents=True, exist_ok=True)
    if manifest["source"] == "ons" and dataset in LOAD_DATASETS:
        valid, rejected, stats = load_frame(manifest["path"], manifest, contract)
        batches = [("data", valid, rejected, stats)]
    elif manifest["source"] == "ons":
        valid, rejected, stats = ons_frame(manifest["path"], manifest, contract)
        batches = [("data", valid, rejected, stats)]
    elif dataset in {"merge_daily", "gfs_0p25", "ecmwf_ifs_0p25"}:
        valid, rejected, stats = grib_frames(manifest["path"], manifest, bbox)
        batches = [("data", valid, rejected, stats)]
    elif manifest["source"] == "inmet":
        batches = inmet_frames(manifest["path"], manifest)
    else:
        raise ValueError(f"Adaptador Silver não habilitado: {dataset}")
    files, reports = [], []
    for name, valid, rejected, stats in batches:
        for kind, table in [("valid", valid), ("quarantine", rejected)]:
            target = destination / f"{name}.{kind}.parquet"
            temporary = target.with_suffix(".part")
            table.write_parquet(temporary, compression="zstd")
            temporary.replace(target)
            files.append(str(target))
        reports.append({**stats, "valid_rows": valid.height, "rejected_rows": rejected.height})
    valid_rows = sum(r["valid_rows"] for r in reports)
    rejected_rows = sum(r["rejected_rows"] for r in reports)
    fraction = rejected_rows / max(valid_rows + rejected_rows, 1)
    report = {"status": "published" if fraction <= max_invalid and valid_rows else "quality_failed",
              "built_at": utcnow(), "version": version, "source_manifest": manifest,
              "valid_rows": valid_rows, "rejected_rows": rejected_rows, "invalid_fraction": fraction,
              "files": files, "batches": reports}
    atomic_json(success, report)
    return report
