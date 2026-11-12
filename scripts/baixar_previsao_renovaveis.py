"""Baixa previsões arquivadas (GFS e ECMWF, 48 h antes) onde estão as usinas eólicas e solares.

As usinas são agrupadas em células de 1 grau, e cada célula guarda a capacidade instalada, que serve de peso.
Capitais entram como aproximação da geração distribuída (telhados). As variáveis arquivadas começam em fev/2024.
Dados: Open-Meteo, CC-BY 4.0, API gratuita para uso não comercial. Saída: data/gold/previsao_renovaveis.parquet.

Executar: .\\.venv\\Scripts\\python.exe scripts/baixar_previsao_renovaveis.py [--dias 3 4]
Com --dias N (N ≠ 2), grava data/gold/previsao_renovaveis_dN.parquet com rodadas emitidas N dias antes (para D+2, D+3...).
"""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire import DATA_DIR, Store, resolve_data_path  # noqa: E402
from models.dados import CIDADES_SUBSISTEMA, conectar  # noqa: E402

BASE = "https://previous-runs-api.open-meteo.com/v1/forecast?"
INICIO = date(2024, 2, 1)
DATASET = "previous_runs_renovaveis"
BASES = {"wind_speed_100m": "vento100", "shortwave_radiation": "radiacao", "cloud_cover": "nuvens"}


def variaveis(dia):
    return {f"{origem}_previous_day{dia}": curto for origem, curto in BASES.items()}


def destino(dia):
    return DATA_DIR / ("gold/previsao_renovaveis.parquet" if dia == 2 else f"gold/previsao_renovaveis_d{dia}.parquet")
MODELOS = {"gfs_global": "gfs", "ecmwf_ifs025": "ecmwf"}
MAX_CELULAS = 15


def celulas(con):
    """Maiores células de 1 grau por fonte e subsistema, com a capacidade atual como peso."""
    tabela = con.sql("""
        WITH u AS (
            SELECT nom_tipousina AS tipo, id_subsistema AS subsistema, nom_usina_conjunto AS usina, ceg,
                   avg(coalesce(val_latitudesecoletora, val_latitudepontoconexao)) AS lat, avg(coalesce(val_longitudesecoletora, val_longitudepontoconexao)) AS lon,
                   arg_max(val_capacidadeinstalada, _event_time_source) AS capacidade
            FROM silver_fator_capacidade_2 GROUP BY ALL)
        SELECT CASE tipo WHEN 'Eólica' THEN 'eolica' ELSE 'solar' END AS fonte, subsistema, round(lat) AS lat_c, round(lon) AS lon_c,
               sum(lat * capacidade) / sum(capacidade) AS lat, sum(lon * capacidade) / sum(capacidade) AS lon, sum(capacidade) AS peso
        FROM u WHERE lat IS NOT NULL AND capacidade > 0 GROUP BY ALL""").df()
    tabela = tabela.sort_values("peso", ascending=False).groupby(["fonte", "subsistema"]).head(MAX_CELULAS)
    cidades = [{"fonte": "cidade", "subsistema": "SE" if s == "SECO" else s, "lat": lat, "lon": lon, "peso": 1.0}
               for s, lista in CIDADES_SUBSISTEMA.items() for _, lat, lon in lista]
    return pd.concat([tabela[["fonte", "subsistema", "lat", "lon", "peso"]], pd.DataFrame(cidades)], ignore_index=True).round({"lat": 2, "lon": 2})


def baixar(store, recurso, url, tentativas=6, espera=45):
    pasta = DATA_DIR / "bronze/open_meteo" / DATASET / recurso
    for caminho in sorted(pasta.glob("*.manifest.json"), reverse=True):
        manifesto = json.loads(caminho.read_text(encoding="utf-8"))
        if manifesto.get("url") == url:
            try:
                return json.loads(Path(resolve_data_path(manifesto["path"])).read_text(encoding="utf-8"))["hourly"]
            except (json.JSONDecodeError, KeyError, OSError):
                continue
    limite_estourado = 0
    tentativa = 0
    while True:
        tentativa += 1
        try:
            manifesto = store.fetch("open_meteo", DATASET, recurso, url, context={"role": "archived_forecast", "licence": "CC-BY-4.0"})
            return json.loads(Path(resolve_data_path(manifesto["path"])).read_text(encoding="utf-8"))["hourly"]
        except HTTPError as erro:
            # 429: limite por minuto/hora da API gratuita (pedidos longos contam como várias chamadas). Espera e retoma.
            if erro.code == 429 and limite_estourado < 12:
                limite_estourado += 1
                print(f"{recurso}: limite da API (429), aguardando 15 min ({limite_estourado}/12)", flush=True)
                time.sleep(900)
                continue
            if tentativa >= tentativas:
                raise
            print(f"{recurso}: HTTP {erro.code}, nova tentativa em {espera} s", flush=True)
            time.sleep(espera)
        except (json.JSONDecodeError, KeyError, OSError) as erro:
            if tentativa >= tentativas:
                raise
            print(f"{recurso}: {type(erro).__name__}, nova tentativa em {espera} s", flush=True)
            time.sleep(espera)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias", type=int, nargs="+", default=[2], help="rodadas emitidas N dias antes de cada hora")
    dias = parser.parse_args().dias
    pedidas = {k: v for dia in dias for k, v in variaveis(dia).items()}
    con = conectar()
    locais = celulas(con)
    con.close()
    print(locais.groupby(["fonte", "subsistema"]).agg(pontos=("peso", "size"), peso=("peso", "sum")).round(0).to_string(), flush=True)
    fim_global, partes = date.today() - timedelta(days=1), {dia: [] for dia in dias}
    marca = "" if dias == [2] else "_d" + "_".join(map(str, dias))
    store = Store(DATA_DIR)
    try:
        for i, local in enumerate(locais.itertuples()):
            for ano in range(INICIO.year, fim_global.year + 1):
                inicio, fim = max(INICIO, date(ano, 1, 1)), min(fim_global, date(ano, 12, 31))
                url = BASE + urlencode({"latitude": local.lat, "longitude": local.lon, "hourly": ",".join(pedidas), "models": ",".join(MODELOS),
                                        "start_date": inicio.isoformat(), "end_date": fim.isoformat(), "timezone": "UTC"})
                corpo = baixar(store, f"{local.lat}_{local.lon}_{ano}{marca}".replace("-", "m"), url)
                for dia in dias:
                    d = {"valid_utc": corpo["time"]}
                    for origem, curto in variaveis(dia).items():
                        for modelo, sufixo in MODELOS.items():
                            d[f"{curto}_{sufixo}"] = corpo.get(f"{origem}_{modelo}", [None] * len(corpo["time"]))
                    partes[dia].append(pd.DataFrame(d).assign(fonte=local.fonte, subsistema=local.subsistema, lat=local.lat, lon=local.lon, peso=local.peso))
                time.sleep(3)  # pedidos de um ano com várias variáveis pesam como dezenas de chamadas
            print(f"{i + 1}/{len(locais)}", flush=True)
    finally:
        store.close()
    for dia in dias:
        tabela = pd.concat(partes[dia], ignore_index=True)
        tabela["valid_utc"] = pd.to_datetime(tabela["valid_utc"])
        tabela = tabela.drop_duplicates(["fonte", "subsistema", "lat", "lon", "valid_utc"], keep="last")
        tabela.to_parquet(destino(dia), index=False)
        print(dia, len(tabela), tabela.notna().mean().round(3).to_dict())


if __name__ == "__main__":
    main()
