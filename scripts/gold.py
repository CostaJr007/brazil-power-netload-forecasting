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

-- PLD ESTIMADO (não é a série oficial da CCEE, bloqueada neste ambiente): CMO do ONS limitado
-- ao piso e ao teto horário da ANEEL. O PLD horário existe desde 2021, por isso o JOIN descarta 2020.
-- A hora vem da média das duas meias horas; fuso como publicado pelo ONS (não declarado).
CREATE VIEW vw_pld_estimado_horario AS
WITH h AS (
    SELECT id_subsistema AS subsistema, date_trunc('hour', _event_time_source) AS hora,
           avg(val_cmo) AS cmo_medio, count(*) AS meias_horas
    FROM silver_cmo_semi_horario
    WHERE NOT _is_sin_aggregate
    GROUP BY ALL)
SELECT h.subsistema, h.hora, CAST(h.hora AS DATE) AS data_referencia, h.cmo_medio, h.meias_horas,
       least(greatest(h.cmo_medio, l.pld_min), l.pld_max_horario) AS pld_estimado,
       CASE WHEN h.cmo_medio < l.pld_min THEN 'piso'
            WHEN h.cmo_medio > l.pld_max_horario THEN 'teto_horario'
            ELSE 'cmo' END AS origem
FROM h JOIN pld_limites l ON l.ano = year(h.hora);

-- Média diária do PLD estimado, limitada ao teto estrutural. A view horária não redistribui esse corte entre as horas.
CREATE VIEW vw_pld_estimado_diario AS
SELECT e.subsistema, e.data_referencia, count(*) AS horas,
       least(avg(e.pld_estimado), l.pld_max_estrutural) AS pld_estimado,
       avg(e.pld_estimado) > l.pld_max_estrutural AS teto_estrutural_aplicado
FROM vw_pld_estimado_horario e JOIN pld_limites l ON l.ano = year(e.data_referencia)
GROUP BY e.subsistema, e.data_referencia, l.pld_max_estrutural;

-- ENA por bacia pronta para somar. Desde 2026 o ONS publica as sub-bacias da Amazônia (Madeira, Xingu, Teles Pires...)
-- além da linha AMAZONAS, que é o agregado delas. Nos dias em que há sub-bacias, a linha agregada sai.
CREATE VIEW vw_ena_bacia_sem_dupla_contagem AS
SELECT nom_bacia, data_referencia, ena_bruta_mwmed, ena_bruta_pct_mlt, ena_armazenavel_mwmed
FROM vw_ena_bacia_diaria
WHERE NOT (nom_bacia = 'AMAZONAS' AND data_referencia IN (SELECT data_referencia FROM vw_ena_bacia_diaria WHERE nom_bacia = 'MADEIRA'));

-- Hidrologia por subsistema e SIN. O percentual do SIN é ponderado: não se tira média de percentuais.
CREATE VIEW vw_hidro_subsistema_diaria AS
WITH ena AS (
    SELECT id_subsistema AS subsistema, CAST(_event_time_source AS DATE) AS data_referencia,
           max(ena_bruta_regiao_mwmed) AS ena_mwmed, max(ena_bruta_regiao_percentualmlt) AS ena_pct_mlt,
           max(ena_armazenavel_regiao_mwmed) AS ena_armazenavel_mwmed
    FROM silver_ena_diario_por_subsistema GROUP BY ALL),
ear AS (
    SELECT id_subsistema AS subsistema, CAST(_event_time_source AS DATE) AS data_referencia,
           max(ear_verif_subsistema_mwmes) AS ear_mwmes, max(ear_max_subsistema) AS ear_max_mwmes, max(ear_verif_subsistema_percentual) AS ear_pct
    FROM silver_ear_diario_por_subsistema GROUP BY ALL),
s AS (SELECT * FROM ena FULL JOIN ear USING (subsistema, data_referencia))
SELECT subsistema, data_referencia, ena_mwmed, ena_pct_mlt, ena_armazenavel_mwmed, ear_mwmes, ear_max_mwmes, ear_pct FROM s
UNION ALL
SELECT 'SIN', data_referencia, sum(ena_mwmed), sum(ena_mwmed) / nullif(sum(ena_mwmed / nullif(ena_pct_mlt, 0)), 0), sum(ena_armazenavel_mwmed),
       sum(ear_mwmes), sum(ear_max_mwmes), 100.0 * sum(ear_mwmes) / nullif(sum(ear_max_mwmes), 0)
FROM s GROUP BY data_referencia;

-- Conferência diária: a soma das bacias tem de fechar com a ENA do SIN.
CREATE VIEW vw_conferencia_soma_bacias AS
WITH b AS (SELECT data_referencia, sum(ena_bruta_mwmed) AS soma_bacias_mwmed, count(*) AS bacias FROM vw_ena_bacia_sem_dupla_contagem GROUP BY 1)
SELECT b.data_referencia, b.bacias, b.soma_bacias_mwmed, h.ena_mwmed AS ena_sin_mwmed, b.soma_bacias_mwmed - h.ena_mwmed AS diferenca_mwmed
FROM b JOIN vw_hidro_subsistema_diaria h ON h.subsistema = 'SIN' AND h.data_referencia = b.data_referencia;

-- ENA e EAR por reservatório equivalente (REE), partição sem sobreposição usada no planejamento.
CREATE VIEW vw_ree_diaria AS
WITH ena AS (
    SELECT nom_reservatorioee AS ree, CAST(_event_time_source AS DATE) AS data_referencia, max(ena_bruta_ree_mwmed) AS ena_mwmed, max(ena_bruta_ree_percentualmlt) AS ena_pct_mlt
    FROM silver_ena_diario_por_ree_reservatorio_equivalente_de_energia GROUP BY ALL),
ear AS (
    SELECT nom_ree AS ree, CAST(_event_time_source AS DATE) AS data_referencia, max(ear_verif_ree_mwmes) AS ear_mwmes, max(ear_max_ree) AS ear_max_mwmes, max(ear_verif_ree_percentual) AS ear_pct
    FROM silver_ear_diario_por_ree_reservatorio_equivalente_de_energia GROUP BY ALL)
SELECT * FROM ena FULL JOIN ear USING (ree, data_referencia);

-- Balanço horário do SIN: soma dos 4 subsistemas, só em horas completas.
CREATE VIEW vw_balanco_horario_sin AS
SELECT instante_fonte, sum(carga_mwmed) AS carga_mwmed, sum(eolica_mwmed) AS eolica_mwmed, sum(solar_mwmed) AS solar_mwmed,
       sum(hidraulica_mwmed) AS hidraulica_mwmed, sum(termica_mwmed) AS termica_mwmed, sum(carga_liquida_mwmed) AS carga_liquida_mwmed
FROM vw_balanco_carga_liquida GROUP BY instante_fonte HAVING count(*) = 4;

-- Balanço diário por subsistema e SIN, em MW médios.
CREATE VIEW vw_balanco_diario AS
WITH t AS (
    SELECT subsistema, instante_fonte, carga_mwmed, eolica_mwmed, solar_mwmed, hidraulica_mwmed, termica_mwmed, carga_liquida_mwmed FROM vw_balanco_carga_liquida
    UNION ALL
    SELECT 'SIN', instante_fonte, carga_mwmed, eolica_mwmed, solar_mwmed, hidraulica_mwmed, termica_mwmed, carga_liquida_mwmed FROM vw_balanco_horario_sin)
SELECT subsistema, CAST(instante_fonte AS DATE) AS data_referencia, count(*) AS horas, avg(carga_mwmed) AS carga_mwmed, avg(eolica_mwmed) AS eolica_mwmed,
       avg(solar_mwmed) AS solar_mwmed, avg(hidraulica_mwmed) AS hidraulica_mwmed, avg(termica_mwmed) AS termica_mwmed, avg(carga_liquida_mwmed) AS carga_liquida_mwmed,
       min(carga_liquida_mwmed) AS carga_liquida_min_mwmed, max(carga_liquida_mwmed) AS carga_liquida_max_mwmed
FROM t GROUP BY 1, 2;

-- Eólica e solar somadas por estado: geração, capacidade e fator de capacidade.
CREATE VIEW vw_renovaveis_diario AS
WITH h AS (
    SELECT nom_tipousina AS fonte, id_subsistema AS subsistema, id_estado AS uf, _event_time_source AS instante,
           sum(val_geracaoverificada) AS geracao, sum(val_capacidadeinstalada) AS capacidade
    FROM silver_fator_capacidade_2 GROUP BY ALL)
SELECT fonte, subsistema, uf, CAST(instante AS DATE) AS data_referencia, count(*) AS horas, avg(geracao) AS geracao_mwmed, avg(capacidade) AS capacidade_mw,
       avg(geracao) / nullif(avg(capacidade), 0) AS fator_capacidade
FROM h GROUP BY ALL;

-- Cortes de geração (constrained-off) por dia: ENE energético, CNF confiabilidade, REL elétrico.
CREATE VIEW vw_cortes_renovaveis_diario AS
WITH u AS (
    SELECT 'Solar' AS fonte, id_subsistema AS subsistema, _event_time_source AS instante, cod_razaorestricao AS razao, val_geracao, val_geracaonaorealizadaapurada AS corte FROM silver_restricao_coff_fotovoltaica
    UNION ALL
    SELECT 'Eólica', id_subsistema, _event_time_source, cod_razaorestricao, val_geracao, val_geracaonaorealizadaapurada FROM silver_restricao_coff_eolica_usi),
d AS (
    SELECT fonte, subsistema, CAST(instante AS DATE) AS data_referencia, count(DISTINCT instante) AS periodos, sum(val_geracao) AS g, sum(corte) AS c,
           sum(corte) FILTER (razao = 'ENE') AS c_ene, sum(corte) FILTER (razao = 'CNF') AS c_cnf, sum(corte) FILTER (razao = 'REL') AS c_rel
    FROM u GROUP BY ALL)
SELECT fonte, subsistema, data_referencia, periodos, g / periodos AS geracao_mwmed, coalesce(c, 0) / periodos AS corte_mwmed,
       coalesce(c_ene, 0) / periodos AS corte_energetico_mwmed, coalesce(c_cnf, 0) / periodos AS corte_confiabilidade_mwmed, coalesce(c_rel, 0) / periodos AS corte_eletrico_mwmed,
       coalesce(c, 0) / nullif(g + coalesce(c, 0), 0) AS corte_pct_do_potencial
FROM d;

-- Painel diário do SIN: uma linha por dia com balanço, hidrologia, cortes e preço.
CREATE VIEW vw_painel_energia_diario AS
WITH cmo AS (
    SELECT CAST(_event_time_source AS DATE) AS data_referencia,
           avg(val_cmo) FILTER (id_subsistema = 'SE') AS cmo_se, avg(val_cmo) FILTER (id_subsistema = 'S') AS cmo_s,
           avg(val_cmo) FILTER (id_subsistema = 'NE') AS cmo_ne, avg(val_cmo) FILTER (id_subsistema = 'N') AS cmo_n
    FROM silver_cmo_semi_horario GROUP BY 1),
cortes AS (SELECT data_referencia, sum(corte_mwmed) FILTER (fonte = 'Eólica') AS corte_eolica_mwmed, sum(corte_mwmed) FILTER (fonte = 'Solar') AS corte_solar_mwmed FROM vw_cortes_renovaveis_diario GROUP BY 1),
pld AS (SELECT data_referencia, pld_estimado AS pld_estimado_se FROM vw_pld_estimado_diario WHERE subsistema = 'SE')
SELECT b.data_referencia, b.horas, b.carga_mwmed, b.eolica_mwmed, b.solar_mwmed, b.hidraulica_mwmed, b.termica_mwmed, b.carga_liquida_mwmed,
       b.carga_liquida_max_mwmed - b.carga_liquida_min_mwmed AS rampa_carga_liquida_mwmed,
       h.ena_mwmed, h.ena_pct_mlt, h.ear_pct, c.corte_eolica_mwmed, c.corte_solar_mwmed, cmo.cmo_se, cmo.cmo_s, cmo.cmo_ne, cmo.cmo_n, p.pld_estimado_se,
       concat_ws(',', CASE WHEN b.horas < 24 THEN 'balanco_incompleto' END, CASE WHEN h.ena_mwmed IS NULL THEN 'ena' END, CASE WHEN h.ear_pct IS NULL THEN 'ear' END,
                 CASE WHEN c.data_referencia IS NULL THEN 'cortes' END, CASE WHEN cmo.cmo_se IS NULL THEN 'cmo' END) AS fontes_ausentes
FROM vw_balanco_diario b
LEFT JOIN vw_hidro_subsistema_diaria h ON h.subsistema = 'SIN' AND h.data_referencia = b.data_referencia
LEFT JOIN cortes c ON c.data_referencia = b.data_referencia
LEFT JOIN cmo ON cmo.data_referencia = b.data_referencia
LEFT JOIN pld p ON p.data_referencia = b.data_referencia
WHERE b.subsistema = 'SIN';

-- Cada fonte chega em um ritmo: última data publicada e última coleta, para saber o que já está disponível hoje.
CREATE VIEW vw_frescor_fontes AS
WITH f AS (
    SELECT 'carga_verificada' AS fonte, CAST(max(timezone('UTC', interval_end_utc)) - INTERVAL 3 HOUR - INTERVAL 1 SECOND AS DATE) AS ultima_referencia, max(_available_at_utc) AS ultima_coleta FROM silver_carga_energia_verificada
    UNION ALL SELECT 'carga_programada', CAST(max(timezone('UTC', interval_end_utc)) - INTERVAL 3 HOUR - INTERVAL 1 SECOND AS DATE), max(_available_at_utc) FROM silver_carga_energia_programada
    UNION ALL SELECT 'balanco_energia', CAST(max(_event_time_source) AS DATE), max(_available_at_utc) FROM silver_balanco_energia_subsistema
    UNION ALL SELECT 'cmo_semi_horario', CAST(max(_event_time_source) AS DATE), max(_available_at_utc) FROM silver_cmo_semi_horario
    UNION ALL SELECT 'ear_subsistema', CAST(max(_event_time_source) AS DATE), max(_available_at_utc) FROM silver_ear_diario_por_subsistema
    UNION ALL SELECT 'ena_subsistema', CAST(max(_event_time_source) AS DATE), max(_available_at_utc) FROM silver_ena_diario_por_subsistema
    UNION ALL SELECT 'ena_bacia', CAST(max(_event_time_source) AS DATE), max(_available_at_utc) FROM silver_ena_diario_por_bacia
    UNION ALL SELECT 'eolica_solar_usinas', CAST(max(_event_time_source) AS DATE), max(_available_at_utc) FROM silver_fator_capacidade_2
    UNION ALL SELECT 'cortes_solar', CAST(max(_event_time_source) AS DATE), max(_available_at_utc) FROM silver_restricao_coff_fotovoltaica
    UNION ALL SELECT 'cortes_eolica', CAST(max(_event_time_source) AS DATE), max(_available_at_utc) FROM silver_restricao_coff_eolica_usi
    UNION ALL SELECT 'chuva_merge', max(data_referencia), NULL FROM vw_chuva_observada_bacia_diaria)
SELECT fonte, ultima_referencia, date_diff('day', ultima_referencia, CAST(current_timestamp AT TIME ZONE 'America/Sao_Paulo' AS DATE)) AS dias_de_atraso, ultima_coleta
FROM f;
"""


def snake(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def create_pld_limits(con):
    """Expõe configs/pld_limits.json como a view pld_limites (consumida pelas views de PLD estimado)."""
    limits = json.loads((ROOT / "configs/pld_limits.json").read_text(encoding="utf-8"))["limits"]
    rows = ", ".join(f"({r['ano']}, {r['pld_min']}, {r['pld_max_estrutural']}, {r['pld_max_horario']})" for r in limits)
    con.execute("CREATE VIEW pld_limites AS SELECT * FROM (VALUES " + rows +
                ") AS t(ano, pld_min, pld_max_estrutural, pld_max_horario)")


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
        create_pld_limits(con)
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
