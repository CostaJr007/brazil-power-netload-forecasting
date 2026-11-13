"""Download wind, solar radiation, humidity and cloud cover FORECAST 48 h ahead (GFS via Open-Meteo), from Feb 2024.

Same logic as baixar_temperatura_prevista.py; these variables are not archived before 2024.
Data: Open-Meteo, CC-BY 4.0, free API for non-commercial use.
"""
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
INICIO = date(2024, 2, 1)
NOMES = {"shortwave_radiation_previous_day2": "radiacao_prev", "wind_speed_10m_previous_day2": "vento_prev",
         "relative_humidity_2m_previous_day2": "umidade_prev", "cloud_cover_previous_day2": "nuvens_prev"}


def ler_corpo(manifesto):
    return json.loads(Path(resolve_data_path(manifesto["path"])).read_text(encoding="utf-8"))["hourly"]


def ja_baixado(recurso, url):
    """Reuse a valid Bronze response for the same URL, avoiding repeated API calls."""
    for caminho in sorted((DATA_DIR / "bronze/open_meteo/gfs_previous_runs_extras" / recurso).glob("*.manifest.json"), reverse=True):
        manifesto = json.loads(caminho.read_text(encoding="utf-8"))
        if manifesto.get("url") == url:
            try:
                return ler_corpo(manifesto)
            except (json.JSONDecodeError, KeyError, OSError):
                continue
    return None


def baixar(store, recurso, url, tentativas=5, espera=30):
    """The API sometimes fails transiently (network timeout or an error text with HTTP 200): retry."""
    pronto = ja_baixado(recurso, url)
    if pronto is not None:
        return pronto
    for tentativa in range(1, tentativas + 1):
        try:
            return ler_corpo(store.fetch("open_meteo", "gfs_previous_runs_extras", recurso, url,
                                         context={"role": "archived_forecast", "licence": "CC-BY-4.0"}))
        except (json.JSONDecodeError, KeyError, OSError) as erro:
            if tentativa == tentativas:
                raise
            print(f"{recurso}: {type(erro).__name__}, retrying in {espera} s", flush=True)
            time.sleep(espera)


def main():
    fim_global = date.today() - timedelta(days=1)
    store, tabelas = Store(DATA_DIR), []
    try:
        for subsistema, cidades in CIDADES_SUBSISTEMA.items():
            for cidade, lat, lon in cidades:
                for ano in range(INICIO.year, fim_global.year + 1):
                    inicio, fim = max(INICIO, date(ano, 1, 1)), min(fim_global, date(ano, 12, 31))
                    url = BASE + urlencode({"latitude": lat, "longitude": lon, "hourly": ",".join(NOMES), "models": "gfs_global",
                                            "start_date": inicio.isoformat(), "end_date": fim.isoformat(), "timezone": "UTC"})
                    corpo = baixar(store, f"{cidade}_{ano}", url)
                    tabelas.append(pl.DataFrame({"valid_utc": corpo["time"], **{novo: corpo[origem] for origem, novo in NOMES.items()}},
                                                schema_overrides={novo: pl.Float64 for novo in NOMES.values()})
                                   .with_columns(pl.col("valid_utc").str.to_datetime("%Y-%m-%dT%H:%M"),
                                                 pl.lit(cidade).alias("cidade"), pl.lit(subsistema).alias("subsistema")))
                    time.sleep(1.0)
                print(cidade, "ok", flush=True)
    finally:
        store.close()
    tabela = pl.concat(tabelas).unique(subset=["cidade", "valid_utc"], keep="last").sort("cidade", "valid_utc")
    tabela.write_parquet(DATA_DIR / "gold/previsao_vento_sol.parquet", compression="zstd")
    print(tabela.null_count())


if __name__ == "__main__":
    main()
