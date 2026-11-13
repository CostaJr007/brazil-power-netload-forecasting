"""Readers of the Gold views for modelling, plus data cleaning (night-time solar, frozen values, zero load,
half-published schedules) and the holiday calendar.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
from dateutil.easter import easter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from acquire import DATA_DIR  # noqa: E402

# Highest-load states of each subsystem: São Paulo's temperature weighs more than Acre's.
ESTADOS_SUBSISTEMA = {"SECO": ["SP", "RJ", "MG"], "S": ["RS", "PR", "SC"], "NE": ["BA", "PE", "CE"], "N": ["PA", "MA", "AM"]}

# Capitals used for forecast temperature (public coordinates): (name, latitude, longitude).
CIDADES_SUBSISTEMA = {
    "SECO": [("sao_paulo", -23.55, -46.63), ("rio_de_janeiro", -22.91, -43.17), ("belo_horizonte", -19.92, -43.94), ("brasilia", -15.79, -47.88)],
    "S": [("porto_alegre", -30.03, -51.23), ("curitiba", -25.43, -49.27), ("florianopolis", -27.60, -48.55)],
    "NE": [("salvador", -12.97, -38.50), ("recife", -8.05, -34.88), ("fortaleza", -3.73, -38.52)],
    "N": [("belem", -1.46, -48.49), ("sao_luis", -2.53, -44.30), ("manaus", -3.12, -60.02)],
}

# Brazil has had no daylight saving since 2019; UTC−3 is a good approximation for daily aggregates.
UTC_PARA_LOCAL = "- INTERVAL 3 HOUR"


def conectar():
    return duckdb.connect(str(DATA_DIR / "gold/energia.duckdb"), read_only=True)


def feriados_nacionais(ano):
    """National holidays plus the optional days with the largest effect on load (Carnival, Corpus Christi)."""
    pascoa = easter(ano)
    fixos = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (12, 25)]
    if ano >= 2024:
        fixos.append((11, 20))  # Black Consciousness Day: national holiday since Law 14,759/2023.
    moveis = [pascoa - timedelta(days=d) for d in (48, 47, 2)] + [pascoa + timedelta(days=60)]
    return {date(ano, m, d) for m, d in fixos} | set(moveis)


def carregar_bacias(con):
    """Basin × day panel with inflow (ENA) and observed MERGE rain."""
    frame = con.sql("""
        SELECT ena_nom_bacia AS bacia, data_referencia AS data, ena_bruta_mwmed AS ena, chuva_mm AS chuva
        FROM vw_chuva_x_ena_bacia
        WHERE ena_bruta_mwmed IS NOT NULL AND chuva_mm IS NOT NULL""").df()
    frame["data"] = pd.to_datetime(frame["data"])
    return frame


def carregar_carga(con):
    """Daily load per subsystem; only complete days (48 half-hours) enter each series."""
    frame = con.sql(f"""
        WITH d AS (
            SELECT subsistema, CAST(timezone('UTC', inicio_utc) {UTC_PARA_LOCAL} AS DATE) AS data,
                   avg(carga_verificada_mwmed) AS carga, count(carga_verificada_mwmed) AS n_v,
                   avg(carga_programada_mwmed) AS programada, count(carga_programada_mwmed) AS n_p
            FROM vw_carga_prevista_vs_verificada GROUP BY ALL)
        SELECT subsistema, data,
               CASE WHEN n_v = 48 THEN carga END AS carga,
               CASE WHEN n_p = 48 THEN programada END AS programada
        FROM d ORDER BY 1, 2""").df()
    frame["data"] = pd.to_datetime(frame["data"])
    return frame


def carregar_carga_horaria(con):
    """Hourly load (local time approximated as UTC−3); only hours with both half-hours enter."""
    frame = con.sql(f"""
        WITH h AS (
            SELECT subsistema, date_trunc('hour', timezone('UTC', inicio_utc) {UTC_PARA_LOCAL}) AS instante,
                   avg(carga_verificada_mwmed) AS carga, count(carga_verificada_mwmed) AS n_v,
                   avg(carga_programada_mwmed) AS programada, count(carga_programada_mwmed) AS n_p
            FROM vw_carga_prevista_vs_verificada GROUP BY ALL)
        SELECT subsistema, instante,
               CASE WHEN n_v = 2 THEN carga END AS carga,
               CASE WHEN n_p = 2 THEN programada END AS programada
        FROM h ORDER BY 1, 2""").df()
    frame["instante"] = pd.to_datetime(frame["instante"])
    return frame


def carregar_extras(con):
    """Per subsystem: observed weather (INMET, highest-load states), storage, inflow and daily generation."""
    saida = {}
    for subsistema, estados in ESTADOS_SUBSISTEMA.items():
        codigo = "SE" if subsistema == "SECO" else subsistema
        lista = ", ".join(f"'{uf}'" for uf in estados)
        clima = con.sql(f"""
            WITH e AS (
                SELECT station_id, CAST(timezone('UTC', observed_at_utc) {UTC_PARA_LOCAL} AS DATE) AS data,
                       avg(air_temperature_c) FILTER (air_temperature_c BETWEEN -15 AND 50) AS temp,
                       max(air_temperature_c) FILTER (air_temperature_c BETWEEN -15 AND 50) AS temp_max,
                       sum(greatest(radiacao_global_kj_m2, 0)) AS radiacao, avg(wind_speed_m_s) AS vento,
                       avg(umidade_relativa_do_ar_horaria) AS umidade, sum(precipitation_mm) AS chuva
                FROM silver_automatic_stations_annual
                WHERE regexp_extract(_zip_member, 'INMET_[A-Z]+_([A-Z]{{2}})_', 1) IN ({lista})
                GROUP BY ALL)
            SELECT data, avg(temp) AS temp, avg(temp_max) AS temp_max, avg(radiacao) AS radiacao, avg(vento) AS vento,
                   avg(umidade) AS umidade, avg(chuva) AS chuva
            FROM e GROUP BY 1""").df().set_index("data")
        ear = con.sql(f"SELECT data_referencia AS data, ear_pct AS ear FROM vw_ear_subsistema_diaria WHERE subsistema = '{codigo}'").df().set_index("data")
        ena = con.sql(f"""SELECT CAST(_event_time_source AS DATE) AS data, max(ena_bruta_regiao_percentualmlt) AS ena_pct
                          FROM silver_ena_diario_por_subsistema WHERE id_subsistema = '{codigo}' GROUP BY 1""").df().set_index("data")
        geracao = con.sql(f"""SELECT CAST(instante_fonte AS DATE) AS data, avg(eolica_mwmed) eolica, avg(solar_mwmed) solar,
                                     avg(hidraulica_mwmed) hidraulica, avg(termica_mwmed) termica
                              FROM vw_balanco_carga_liquida WHERE subsistema = '{codigo}' GROUP BY 1""").df().set_index("data")
        tabela = clima.join([ear, ena, geracao], how="outer")
        tabela.index = pd.to_datetime(tabela.index)
        saida[subsistema] = tabela.sort_index().asfreq("D")
    return saida


HORAS_SEM_SOL = {20, 21, 22, 23, 0, 1, 2, 3, 4}  # local time: the sun is below the horizon everywhere in Brazil
LIMIAR_MW = 50.0
HORAS_CONGELADO = 4


def tratar_balanco(frame):
    """Mark as missing what is physically impossible or source filler. Missing, never zero.

    - load ≤ 0 (e.g. South on 2018-11-04);
    - solar > 50 MW between 8 pm and 4:59 am local time (e.g. SE in 2022–2023);
    - wind or solar identical for 4 h or more above 50 MW (e.g. SE solar stuck at 2,876 MW all night on 2024-11-10).
    """
    frame = frame.sort_values(["subsistema", "instante"]).copy()
    frame["carga"] = frame["carga"].where(frame["carga"] > 0)
    noite = frame["instante"].dt.hour.isin(HORAS_SEM_SOL)
    frame["solar"] = frame["solar"].mask(noite & (frame["solar"] > LIMIAR_MW))
    for coluna in ("eolica", "solar"):
        v = frame[coluna]
        bloco = ((v != v.groupby(frame["subsistema"]).shift()) | v.isna()).cumsum()
        tamanho = v.groupby([frame["subsistema"], bloco]).transform("size")
        frame[coluna] = v.mask((tamanho >= HORAS_CONGELADO) & (v > LIMIAR_MW))
    return frame.reset_index(drop=True)


def carregar_balanco_horario(con):
    """Load, wind and solar (plants + rooftop) per subsystem and hour, as in the ONS balance, already cleaned."""
    frame = con.sql("""SELECT subsistema, instante_fonte AS instante, carga_mwmed AS carga, eolica_mwmed AS eolica, solar_mwmed AS solar
                       FROM vw_balanco_carga_liquida ORDER BY 1, 2""").df()
    frame["instante"] = pd.to_datetime(frame["instante"])
    return tratar_balanco(frame)


def carregar_dessem(con):
    """ONS schedule published the day before (DESSEM), as hourly means. Block 1 = 00:00–00:30.

    Some days are half-published (136 subsystem-days between Jul 2025 and Jan 2026): only hours with both half-hours enter.
    """
    frame = con.sql("""
        SELECT cod_subsistema AS subsistema,
               CAST(_event_time_source AS TIMESTAMP) + to_hours(CAST(floor((num_patamar - 1) / 2) AS INTEGER)) AS instante,
               avg(val_demanda) AS demanda, avg(val_ger_eolica) AS eolica, avg(val_ger_fotovoltaica + val_ger_mmgd) AS solar
        FROM silver_balanco_dessem_detalhe GROUP BY 1, 2 HAVING count(DISTINCT num_patamar) = 2 ORDER BY 1, 2""").df()
    frame["instante"] = pd.to_datetime(frame["instante"])
    return frame


def carregar_previsao_renovaveis(dia=2):
    """Forecasts issued `dia` days before (48 h by default) over plant regions, capacity-weighted. Key: (subsystem, source)."""
    frame = pd.read_parquet(DATA_DIR / ("gold/previsao_renovaveis.parquet" if dia == 2 else f"gold/previsao_renovaveis_d{dia}.parquet"))
    return agregar_previsoes(frame)


def agregar_previsoes(frame):
    """Points (source, subsystem, lat, lon, weight, valid_utc, variables) → weighted mean per (subsystem, source) and local hour."""
    frame = frame.copy()
    frame["instante"] = pd.to_datetime(frame["valid_utc"]) - pd.Timedelta(hours=3)
    colunas = [c for c in frame.columns if c.split("_")[0] in {"vento100", "radiacao", "nuvens"}]
    # Model rounding produces radiation of −17 W/m² and cloud cover of −1% or 101%: clip back to the physical range.
    for c in colunas:
        frame[c] = frame[c].clip(lower=0, upper=100 if c.startswith("nuvens") else None)
    saida = {}
    for (subsistema, fonte), g in frame.groupby(["subsistema", "fonte"]):
        pesos = g["peso"]
        ponderado = g[colunas].mul(pesos, axis=0).assign(instante=g["instante"])
        soma_pesos = g[colunas].notna().mul(pesos, axis=0).assign(instante=g["instante"])
        media = ponderado.groupby("instante").sum(min_count=1) / soma_pesos.groupby("instante").sum().replace(0, float("nan"))
        saida[(subsistema, fonte)] = media
    return saida


def carregar_previstas_extras():
    """Wind, radiation, humidity and cloud cover forecast 48 h ahead (only from 2024), per city × local time."""
    frame = pd.read_parquet(DATA_DIR / "gold/previsao_vento_sol.parquet")
    frame["instante"] = pd.to_datetime(frame["valid_utc"]) - pd.Timedelta(hours=3)
    return frame


def carregar_temperatura_prevista(dia=2):
    """Temperature per city × local time: forecast `dia` days before, plus analysis (perfect-foresight bound).

    dia=2 returns column temp_prev_48h (used by the D+1 models); other days return temp_prev.
    """
    if dia == 2:
        frame, coluna = pd.read_parquet(DATA_DIR / "gold/temperatura_prevista.parquet"), "temp_prev_48h"
    else:
        frame, coluna = pd.read_parquet(DATA_DIR / f"gold/temperatura_prevista_d{dia}.parquet"), "temp_prev"
    frame["instante"] = pd.to_datetime(frame["valid_utc"]) - pd.Timedelta(hours=3)
    return frame[["subsistema", "cidade", "instante", coluna, "temp_analise"]]


def carregar_temperatura(con):
    """Daily mean and maximum temperature per state, from INMET automatic stations."""
    frame = con.sql(f"""
        WITH e AS (
            SELECT regexp_extract(_zip_member, 'INMET_[A-Z]+_([A-Z]{{2}})_', 1) AS uf, station_id,
                   CAST(timezone('UTC', observed_at_utc) {UTC_PARA_LOCAL} AS DATE) AS data,
                   avg(air_temperature_c) AS tmed, max(air_temperature_c) AS tmax, count(air_temperature_c) AS horas
            FROM silver_automatic_stations_annual
            WHERE air_temperature_c BETWEEN -15 AND 50
            GROUP BY ALL)
        SELECT uf, data, avg(tmed) AS tmed, avg(tmax) AS tmax
        FROM e WHERE horas >= 20 GROUP BY ALL""").df()
    frame["data"] = pd.to_datetime(frame["data"])
    return frame
