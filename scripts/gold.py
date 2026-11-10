"""Camada Gold: agregados por bacia + views SQL (DuckDB) prontas para análise e modelos.

    Bronze (bytes originais) → Silver (tipado, validado) → Gold (tabelas de negócio)

O que este script faz:
1. Para cada snapshot meteorológico atual (MERGE, GFS, ECMWF), calcula a média
   por bacia ponderada por área (scripts/basins.py) e grava um Parquet por
   snapshot em data/gold/basin_weather/. Snapshots já processados são pulados.
2. Recria o banco data/gold/energia.duckdb só com VIEWS (nenhum dado copiado):
   - silver_<conjunto>: os .valid.parquet ATUAIS de cada conjunto da Silver;
   - vw_*: as tabelas de negócio descritas em docs/gold_views.md.

Executar:  .\\.venv\\Scripts\\python.exe scripts/gold.py
Consultar: .\\.venv\\Scripts\\python.exe -c "import duckdb; print(duckdb.connect('data/gold/energia.duckdb', read_only=True).sql('FROM vw_chuva_x_ena_bacia LIMIT 5'))"
"""
import json
import re
import uuid
from pathlib import Path

import duckdb
import polars as pl

from acquire import DATA_DIR, ROOT, atomic_json, resolve_data_path, utcnow
from basins import basin_means, ena_mapping, grid_weights, load_basins

WEATHER = {"merge_daily": "merge", "gfs_0p25": "gfs", "ecmwf_ifs_0p25": "ecmwf"}
KEYS = ["variable", "unit", "source_variable", "level_type", "level", "step_type",
        "valid_time_utc", "run_time_utc", "interval_start_utc", "interval_end_utc"]

VIEWS = r"""
-- Chuva OBSERVADA por bacia (MERGE/CPTEC: satélite GPM + pluviômetros), um valor por dia.
-- valid_time_utc do MERGE marca o fechamento do acumulado diário; a janela exata
-- (convenção 12 UTC→12 UTC) ainda não foi confirmada no contrato: ver interval_status na Silver.
CREATE VIEW vw_chuva_observada_bacia_diaria AS
SELECT basin_id, basin_name, CAST(valid_time_utc AS DATE) AS data_referencia,
       value AS chuva_mm, coverage AS cobertura_area, cells AS celulas, _source_sha256
FROM gold_basin_weather
WHERE source = 'merge' AND variable = 'precipitation_mm';

-- Chuva PREVISTA por bacia, por rodada e horizonte. ECMWF e GFS acumulam desde o início da rodada;
-- a chuva de cada período é a diferença entre horizontes consecutivos.
CREATE VIEW vw_previsao_chuva_bacia AS
WITH acc AS (
    SELECT source AS modelo, basin_id, basin_name, run_time_utc AS rodada_utc,
           interval_end_utc AS fim_periodo_utc,
           date_diff('hour', run_time_utc, interval_end_utc) AS horizonte_h,
           value AS acumulado_mm, coverage AS cobertura_area
    FROM gold_basin_weather
    WHERE source IN ('ecmwf', 'gfs') AND variable = 'precipitation_mm'
      AND interval_start_utc = run_time_utc)
SELECT *,
       horizonte_h - coalesce(lag(horizonte_h) OVER w, 0) AS periodo_h,
       acumulado_mm - coalesce(lag(acumulado_mm) OVER w, 0) AS chuva_periodo_mm
FROM acc
WINDOW w AS (PARTITION BY modelo, basin_id, rodada_utc ORDER BY horizonte_h);

-- ENA diária por bacia (ONS). Último snapshot atual de cada arquivo; data como publicada (fuso não declarado).
CREATE VIEW vw_ena_bacia_diaria AS
SELECT nom_bacia, CAST(_event_time_source AS DATE) AS data_referencia,
       max(ena_bruta_bacia_mwmed) AS ena_bruta_mwmed,
       max(ena_bruta_bacia_percentualmlt) AS ena_bruta_pct_mlt,
       max(ena_armazenavel_bacia_mwmed) AS ena_armazenavel_mwmed
FROM silver_ena_diario_por_bacia
GROUP BY ALL;

-- A tabela da hipótese: chuva observada na bacia × ENA da mesma bacia, por dia.
-- Só bacias com correspondência explícita de nome (ver basin_ena_mapping).
CREATE VIEW vw_chuva_x_ena_bacia AS
SELECT m.basin_id, m.basin_name, m.ena_nom_bacia, m.match AS tipo_correspondencia,
       coalesce(c.data_referencia, e.data_referencia) AS data_referencia,
       c.chuva_mm, c.cobertura_area, e.ena_bruta_mwmed, e.ena_bruta_pct_mlt
FROM basin_ena_mapping m
JOIN vw_chuva_observada_bacia_diaria c USING (basin_id)
FULL JOIN vw_ena_bacia_diaria e ON e.nom_bacia = m.ena_nom_bacia AND e.data_referencia = c.data_referencia
WHERE m.ena_nom_bacia IS NOT NULL;

-- Carga semi-horária: previsão do ONS × realizado (UTC declarado pela fonte).
-- Para cada área/intervalo fica a versão mais recente de cada série. ATENÇÃO para backtest:
-- a programada "mais recente" pode ter sido revisada; use silver_* e _available_at_utc para a visão "como era no dia".
CREATE VIEW vw_carga_prevista_vs_verificada AS
WITH v AS (
    SELECT *, row_number() OVER (PARTITION BY cod_areacarga, interval_end_utc
                                 ORDER BY source_updated_at_utc DESC NULLS LAST, _available_at_utc DESC) AS rn
    FROM silver_carga_energia_verificada),
p AS (
    SELECT *, row_number() OVER (PARTITION BY cod_areacarga, interval_end_utc ORDER BY _available_at_utc DESC) AS rn
    FROM silver_carga_energia_programada)
SELECT coalesce(v.cod_areacarga, p.cod_areacarga) AS subsistema,
       coalesce(v.interval_start_utc, p.interval_start_utc) AS inicio_utc,
       coalesce(v.interval_end_utc, p.interval_end_utc) AS fim_utc,
       p.val_cargaglobalprogramada AS carga_programada_mwmed,
       v.val_cargaglobal AS carga_verificada_mwmed,
       v.val_cargammgd AS mmgd_mwmed,
       v.val_cargaglobalsmmgd AS carga_sem_mmgd_mwmed,
       v.val_cargaglobal - p.val_cargaglobalprogramada AS erro_previsao_mwmed
FROM (SELECT * FROM v WHERE rn = 1) v
FULL JOIN (SELECT * FROM p WHERE rn = 1) p
  ON v.cod_areacarga = p.cod_areacarga AND v.interval_end_utc = p.interval_end_utc;

-- Balanço horário por subsistema com carga líquida (carga − eólica − solar). Exclui o agregado SIN.
CREATE VIEW vw_balanco_carga_liquida AS
SELECT id_subsistema AS subsistema, _event_time_source AS instante_fonte,
       max(val_carga) AS carga_mwmed, max(val_gereolica) AS eolica_mwmed, max(val_gersolar) AS solar_mwmed,
       max(val_gerhidraulica) AS hidraulica_mwmed, max(val_gertermica) AS termica_mwmed,
       max(val_carga) - coalesce(max(val_gereolica), 0) - coalesce(max(val_gersolar), 0) AS carga_liquida_mwmed
FROM silver_balanco_energia_subsistema
WHERE NOT _is_sin_aggregate
GROUP BY ALL;

-- EAR diária por subsistema e CMO semanal: estado do sistema e preço-sombra.
CREATE VIEW vw_ear_subsistema_diaria AS
SELECT id_subsistema AS subsistema, CAST(_event_time_source AS DATE) AS data_referencia,
       max(ear_verif_subsistema_percentual) AS ear_pct, max(ear_verif_subsistema_mwmes) AS ear_mwmes
FROM silver_ear_diario_por_subsistema GROUP BY ALL;

CREATE VIEW vw_cmo_semanal AS
SELECT id_subsistema AS subsistema, CAST(_event_time_source AS DATE) AS semana,
       max(val_cmomediasemanal) AS cmo_medio, max(val_cmoleve) AS cmo_leve,
       max(val_cmomedia) AS cmo_medio_patamar, max(val_cmopesada) AS cmo_pesada
FROM silver_cmo_semanal GROUP BY ALL;
"""


def snake(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def current_snapshots():
    return json.loads((DATA_DIR / "silver/current.json").read_text(encoding="utf-8"))["snapshots"]


def build_basin_weather(snapshots, basins, log=print):
    """Um Parquet por snapshot meteorológico; reprocessa só o que ainda não existe."""
    out_dir = DATA_DIR / "gold/basin_weather"
    files, built = [], 0
    for snapshot in snapshots:
        manifest = snapshot["source_manifest"]
        source = WEATHER.get(manifest["dataset"])
        if not source:
            continue
        target = out_dir / source / f"{manifest['sha256']}_{snapshot['version']}.parquet"
        files.append(target)
        if target.exists():
            continue
        frame = pl.concat([pl.read_parquet(resolve_data_path(f)) for f in snapshot["files"] if f.endswith(".valid.parquet")], how="diagonal_relaxed")
        frame = frame.filter(pl.col("variable").is_in(["precipitation_mm", "runoff_mm", "temperature_c"]))
        weights = grid_weights(frame["latitude"].unique().to_numpy(), frame["longitude"].unique().to_numpy(),
                               basins, DATA_DIR / "gold/grid_weights")
        result = basin_means(frame, weights, basins, KEYS).with_columns(
            pl.lit(source).alias("source"), pl.lit(manifest["sha256"]).alias("_source_sha256"),
            pl.lit(manifest["resource_id"]).alias("_resource_id"))
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".part")
        result.write_parquet(temporary)
        temporary.replace(target)
        built += 1
    log(f"Gold basin_weather: {built} novos, {len(files)} no total")
    return files, built


def sql_list(paths):
    return "[" + ", ".join("'" + Path(p).as_posix().replace("'", "''") + "'" for p in paths) + "]"


def refresh(log=print):
    """Atualiza agregados e recria as views. Devolve um resumo para o relatório."""
    snapshots = current_snapshots()
    basins = load_basins()
    weather_files, built = build_basin_weather(snapshots, basins, log)
    config = json.loads((ROOT / "configs/basin_mapping.json").read_text(encoding="utf-8"))
    by_dataset = {}
    for snapshot in snapshots:
        valid = [resolve_data_path(f) for f in snapshot["files"] if f.endswith(".valid.parquet")]
        by_dataset.setdefault(snapshot["source_manifest"]["dataset"], []).extend(valid)
    ena_files = by_dataset.get("ena-diario-por-bacia", [])
    ena_names = pl.concat([pl.read_parquet(f, columns=["nom_bacia"]) for f in ena_files])["nom_bacia"].unique().to_list() if ena_files else []
    mapping = ena_mapping(basins, ena_names, config["overrides"])
    gold = DATA_DIR / "gold"
    gold.mkdir(parents=True, exist_ok=True)
    mapping.write_parquet(gold / "basin_ena_mapping.parquet")
    pl.from_pandas(basins.drop(columns="geometry")).write_parquet(gold / "basins.parquet")
    database = gold / "energia.duckdb"
    # Nome temporário único: backfill e coleta agendada podem atualizar a Gold ao mesmo tempo.
    temporary = gold / f"energia.{uuid.uuid4().hex[:8]}.duckdb.part"
    # Banco novo a cada execução e troca no fim: quem estiver lendo nunca vê views pela metade.
    con = duckdb.connect(str(temporary))
    try:
        for dataset, files in sorted(by_dataset.items()):
            if files:
                con.execute(f"CREATE VIEW silver_{snake(dataset)} AS SELECT * FROM read_parquet({sql_list(files)}, union_by_name = true)")
        existing = [p for p in weather_files if p.exists()]
        if existing:
            con.execute(f"CREATE VIEW gold_basin_weather AS SELECT * FROM read_parquet({sql_list(existing)}, union_by_name = true)")
        con.execute(f"CREATE VIEW basin_ena_mapping AS SELECT * FROM read_parquet('{(gold / 'basin_ena_mapping.parquet').as_posix()}')")
        con.execute(f"CREATE VIEW basins AS SELECT * FROM read_parquet('{(gold / 'basins.parquet').as_posix()}')")
        created, skipped = [], []
        # Comentários "--" saem antes de separar por ";" (eles podem conter ponto e vírgula).
        code = "\n".join(line for line in VIEWS.splitlines() if not line.strip().startswith("--"))
        for statement in [s.strip() for s in code.split(";") if s.strip()]:
            name = re.search(r"CREATE VIEW (\w+)", statement).group(1)
            try:
                con.execute(statement)
                con.execute(f"SELECT * FROM {name} LIMIT 0")
                created.append(name)
            except duckdb.Error as exc:
                # View depende de conjunto ainda ausente (ex.: sem backfill): registra e segue.
                con.execute(f"DROP VIEW IF EXISTS {name}")
                skipped.append({"view": name, "reason": str(exc).splitlines()[0][:200]})
    except Exception:
        con.close()
        temporary.unlink(missing_ok=True)
        raise
    con.close()
    temporary.replace(database)
    summary = {"refreshed_at": utcnow(), "database": str(database), "views": created, "skipped_views": skipped,
               "basin_weather_files": len(weather_files), "basin_weather_built": built,
               "basins_repaired": int(basins["geometry_repaired"].sum()),
               "ena_mapping": mapping.group_by("match").len().to_dicts()}
    atomic_json(ROOT / "docs/inventory/gold_status.json", summary)
    log(f"Gold: {len(created)} views criadas, {len(skipped)} puladas")
    return summary


if __name__ == "__main__":
    print(json.dumps(refresh(), ensure_ascii=False, indent=2, default=str))
