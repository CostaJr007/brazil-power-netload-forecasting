"""Baixa temperaturas PREVISTAS arquivadas (GFS, via Open-Meteo Previous Runs API) para capitais.

Por que existe: para avaliar um modelo de D+1 é preciso saber o que a previsão dizia NA VÉSPERA,
não a temperatura que de fato ocorreu. O ECMWF deste projeto só tem rodadas recentes.

temperature_2m_previous_day2 = valor previsto 48 h antes do horário válido. Para qualquer hora do
dia T, essa rodada já está disponível de madrugada em T−1. Já previous_day1 (24 h) NÃO serve: para
as últimas horas de T ela vem de uma rodada do próprio dia T.
Para D+2 e D+3 a regra é a mesma, um dia mais cedo a cada passo: previous_day3 e previous_day4.
temperature_2m é a análise de curto prazo: serve só para medir o limite de uma previsão perfeita.

Respostas brutas ficam na Bronze; a tabela de uso fica em data/gold/temperatura_prevista.parquet
(dia 2) ou temperatura_prevista_dN.parquet (outros dias, coluna temp_prev).
Dados: Open-Meteo, CC-BY 4.0, API gratuita para uso não comercial (< 10.000 chamadas por dia).

Executar: .\\.venv\\Scripts\\python.exe scripts/baixar_temperatura_prevista.py [--dias 3 4]
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
INICIO = date(2021, 3, 23)  # Primeiro dia com GFS arquivado na API.


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
            print(f"{recurso}: {type(erro).__name__}, nova tentativa em {espera} s", flush=True)
            time.sleep(espera)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, nargs="+", default=[2], help="rodadas emitidas N dias antes de cada hora")
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
                    time.sleep(1.0)  # Educado com a API gratuita: bem abaixo de 600 chamadas por minuto.
                print(cidade, "ok", flush=True)
    finally:
        store.close()
    for dia in dias:
        tabela = pl.concat(tabelas[dia]).unique(subset=["cidade", "valid_utc"], keep="last").sort("cidade", "valid_utc")
        tabela.write_parquet(DATA_DIR / ("gold/temperatura_prevista.parquet" if dia == 2 else f"gold/temperatura_prevista_d{dia}.parquet"), compression="zstd")
        print(dia, tabela.height, tabela.null_count().row(0, named=True))


if __name__ == "__main__":
    main()
