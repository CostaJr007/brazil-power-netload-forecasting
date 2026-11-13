"""Download archived temperature FORECASTS (GFS, via the Open-Meteo Previous Runs API) for capital cities.

Why: evaluating a D+1 model requires knowing what the forecast said THE DAY BEFORE,
not the temperature that actually occurred. This project's ECMWF archive only has recent runs.

temperature_2m_previous_day2 = value forecast 48 h before the valid time. For any hour of
day T, that run is already available early on T−1. previous_day1 (24 h) does NOT work: for
the last hours of T it comes from a run issued on T itself.
For D+2 and D+3 the rule is the same, one day earlier each step: previous_day3 and previous_day4.
temperature_2m is the short-range analysis: used only to measure the perfect-forecast bound.

Raw responses stay in Bronze; the working table is data/gold/temperatura_prevista.parquet
(day 2) or temperatura_prevista_dN.parquet (other days, column temp_prev).
Data: Open-Meteo, CC-BY 4.0, free API for non-commercial use (< 10,000 calls per day).

Run: .\\.venv\\Scripts\\python.exe scripts/baixar_temperatura_prevista.py [--dias 3 4]
"""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire import DATA_DIR, Store, resolve_data_path  # noqa: E402
from models.dados import CIDADES_SUBSISTEMA  # noqa: E402

BASE = "https://previous-runs-api.open-meteo.com/v1/forecast?"
INICIO = date(2021, 3, 23)  # First day with archived GFS in the API.


def url_cidade(lat, lon, inicio, fim, dias):
    variaveis = ",".join(["temperature_2m"] + [f"temperature_2m_previous_day{d}" for d in dias])
    return BASE + urlencode({"latitude": lat, "longitude": lon, "hourly": variaveis, "models": "gfs_global",
                             "start_date": inicio.isoformat(), "end_date": fim.isoformat(), "timezone": "UTC"})


def buscar(store, recurso, url, tentativas=6, espera=45):
    for tentativa in range(1, tentativas + 1):
        try:
            manifesto = store.fetch("open_meteo", "gfs_previous_runs", recurso, url, context={"role": "archived_forecast", "licence": "CC-BY-4.0"})
            return manifesto, json.loads(Path(resolve_data_path(manifesto["path"])).read_text(encoding="utf-8"))["hourly"]
        except (json.JSONDecodeError, KeyError, OSError) as erro:
            if tentativa == tentativas:
                raise
            print(f"{recurso}: {type(erro).__name__}, retrying in {espera} s", flush=True)
            time.sleep(espera)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, nargs="+", default=[2], help="runs issued N days before each hour")
    dias = parser.parse_args().dias
    marca = "" if dias == [2] else "_d" + "_".join(map(str, dias))
    fim_global = date.today() - timedelta(days=1)
    store, tabelas = Store(DATA_DIR), {dia: [] for dia in dias}
    try:
        for subsistema, cidades in CIDADES_SUBSISTEMA.items():
            for cidade, lat, lon in cidades:
                for ano in range(INICIO.year, fim_global.year + 1):
                    inicio, fim = max(INICIO, date(ano, 1, 1)), min(fim_global, date(ano, 12, 31))
                    manifesto, corpo = buscar(store, f"{cidade}_{ano}{marca}", url_cidade(lat, lon, inicio, fim, dias))
                    for dia in dias:
                        coluna = "temp_prev_48h" if dia == 2 else "temp_prev"
                        tabelas[dia].append(pl.DataFrame({"valid_utc": corpo["time"], "temp_analise": corpo["temperature_2m"],
                                                          coluna: corpo[f"temperature_2m_previous_day{dia}"]},
                                                         schema_overrides={"temp_analise": pl.Float64, coluna: pl.Float64})
                                            .with_columns(pl.col("valid_utc").str.to_datetime("%Y-%m-%dT%H:%M"),
                                                          pl.lit(cidade).alias("cidade"), pl.lit(subsistema).alias("subsistema"),
                                                          pl.lit(manifesto["sha256"]).alias("_source_sha256")))
                    time.sleep(1.0)  # Polite to the free API: well below 600 calls per minute.
                print(cidade, "ok", flush=True)
    finally:
        store.close()
    for dia in dias:
        tabela = pl.concat(tabelas[dia]).unique(subset=["cidade", "valid_utc"], keep="last").sort("cidade", "valid_utc")
        tabela.write_parquet(DATA_DIR / ("gold/temperatura_prevista.parquet" if dia == 2 else f"gold/temperatura_prevista_d{dia}.parquet"), compression="zstd")
        print(dia, tabela.height, tabela.null_count().row(0, named=True))


if __name__ == "__main__":
    main()
