"""Previsão operacional da carga líquida (carga − eólica − solar) para amanhã e depois de amanhã.

É o "produto" do projeto: em vez de backtest, a previsão que uma mesa receberia hoje, por subsistema e
hora, com as receitas escolhidas em 2025 e confirmadas em 2026 (docs/research/carga_liquida_d1.md e _d2.md).

Insumos:
  - balanço e DESSEM do ONS já tratados na Gold (rode antes scripts/pipeline.py);
  - previsões arquivadas (scripts/baixar_previsao_renovaveis.py e baixar_temperatura_prevista.py, dias 2 e 3),
    que alimentam as anomalias e o treino;
  - previsão do tempo atual do Open-Meteo (CC-BY 4.0, uso não comercial) para os mesmos pontos, guardada na Bronze.

Hora ideal: depois das 20h de Brasília, quando o balanço de ontem já saiu. Antes disso, cada dia é previsto
com o horizonte seguinte (menos informação), e a coluna `horizonte` mostra isso.

Saída: data/gold/previsao_operacional.parquet (acumula por data de decisão) e resumo no terminal.
Executar: .\\.venv\\Scripts\\python.exe scripts/prever_carga_liquida.py [--decisao 2026-11-12]
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire import DATA_DIR, Store, resolve_data_path  # noqa: E402
from baixar_previsao_renovaveis import MODELOS, celulas  # noqa: E402
from models.dados import (CIDADES_SUBSISTEMA, agregar_previsoes, carregar_balanco_horario, carregar_dessem,  # noqa: E402
                          carregar_previsao_renovaveis, carregar_temperatura_prevista, conectar)
from models.operacional import (UM_DIA, aplicar_banda, carga_liquida, dias_completos, historico_liquido,  # noqa: E402
                                horizonte_efetivo, prever_dia, quantis_residuo)

RAIZ = Path(__file__).resolve().parents[1]
API = "https://api.open-meteo.com/v1/forecast?"
RENOVAVEIS = {"wind_speed_100m": "vento100", "shortwave_radiation": "radiacao", "cloud_cover": "nuvens"}
LOTE = 20
BACKTEST = {1: "previsoes_carga_liquida", 2: "previsoes_carga_liquida_dmais2"}


def banda_operacional(atual, receitas, decisao):
    """Carga líquida prevista com banda de 80%: quantis dos erros do backtest do horizonte usado, até a decisão."""
    partes = []
    for (passo, h), pecas in atual.groupby(["passo", "horizonte"]):
        liq = carga_liquida(pecas).merge(carga_liquida(pecas, "ons_ant_semana"), on=["subsistema", "data", "hora"], how="left")
        historico = historico_liquido(pd.read_parquet(DATA_DIR / f"gold/{BACKTEST[h]}.parquet"), receitas[h])
        liq = aplicar_banda(liq, quantis_residuo(historico, decisao))
        partes.append(liq.assign(decisao=decisao, passo=passo, horizonte=h))
    return pd.concat(partes, ignore_index=True)


def buscar(store, recurso, parametros):
    url = API + urlencode(parametros)
    for tentativa in range(1, 5):
        try:
            manifesto = store.fetch("open_meteo", "forecast_operacional", recurso, url, context={"role": "live_forecast", "licence": "CC-BY-4.0"})
            corpo = json.loads(Path(resolve_data_path(manifesto["path"])).read_text(encoding="utf-8"))
            return corpo if isinstance(corpo, list) else [corpo]
        except (OSError, json.JSONDecodeError) as erro:
            if tentativa == 4:
                raise
            print(f"{recurso}: {type(erro).__name__}, nova tentativa em 30 s", flush=True)
            time.sleep(30)


def previsao_atual(store, locais, decisao):
    """Vento, radiação e nuvens (GFS e ECMWF) nos pontos das usinas e capitais; temperatura (GFS) nas capitais."""
    comum = {"forecast_days": 4, "past_days": 2, "timezone": "UTC"}
    partes = []
    for inicio in range(0, len(locais), LOTE):
        lote = locais.iloc[inicio:inicio + LOTE]
        corpos = buscar(store, f"renovaveis_{decisao}_{inicio}", {**comum, "latitude": ",".join(map(str, lote["lat"])),
                        "longitude": ",".join(map(str, lote["lon"])), "hourly": ",".join(RENOVAVEIS), "models": ",".join(MODELOS)})
        for local, corpo in zip(lote.itertuples(), corpos):
            h = corpo["hourly"]
            d = {"valid_utc": h["time"]}
            for origem, curto in RENOVAVEIS.items():
                for modelo, sufixo in MODELOS.items():
                    d[f"{curto}_{sufixo}"] = h.get(f"{origem}_{modelo}", [None] * len(h["time"]))
            partes.append(pd.DataFrame(d).assign(fonte=local.fonte, subsistema=local.subsistema, lat=local.lat, lon=local.lon, peso=local.peso))
        time.sleep(1)
    renovaveis = pd.concat(partes, ignore_index=True)
    renovaveis["valid_utc"] = pd.to_datetime(renovaveis["valid_utc"])
    cidades = [(s, nome, lat, lon) for s, lista in CIDADES_SUBSISTEMA.items() for nome, lat, lon in lista]
    corpos = buscar(store, f"temperatura_{decisao}", {**comum, "latitude": ",".join(str(c[2]) for c in cidades),
                    "longitude": ",".join(str(c[3]) for c in cidades), "hourly": "temperature_2m", "models": "gfs_global"})
    temperatura = pd.concat([pd.DataFrame({"valid_utc": pd.to_datetime(c["hourly"]["time"]), "temp": c["hourly"]["temperature_2m"],
                                           "subsistema": s, "cidade": nome}) for (s, nome, _, _), c in zip(cidades, corpos)], ignore_index=True)
    return renovaveis, temperatura


def juntar_previsoes(arquivadas, atuais):
    """Arquivo (rodadas de N dias antes) onde existe; previsão atual só para as horas que o arquivo ainda não cobre."""
    saida = {}
    for chave in set(arquivadas) | set(atuais):
        a, b = arquivadas.get(chave), atuais.get(chave)
        if a is None or b is None:
            saida[chave] = a if b is None else b
            continue
        saida[chave] = pd.concat([a, b[b.index > a.index.max()]]).sort_index()
    return saida


def juntar_temperatura(arquivada, atual, coluna):
    atual = atual.assign(instante=atual["valid_utc"] - pd.Timedelta(hours=3), temp_analise=float("nan")).rename(columns={"temp": coluna})
    novas = atual[atual["instante"] > arquivada["instante"].max()]
    return pd.concat([arquivada, novas[arquivada.columns]], ignore_index=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisao", default=date.today().isoformat(), help="dia D da decisão; prevê D+1 e D+2")
    decisao = pd.Timestamp(parser.parse_args().decisao)
    con = conectar()
    balanco, dessem, locais = carregar_balanco_horario(con), carregar_dessem(con), celulas(con)
    con.close()
    # Nada posterior à decisão entra: simula exatamente o que existia na noite de D.
    balanco = balanco[balanco["instante"] < decisao]
    dessem = dessem[dessem["instante"] < decisao + 2 * UM_DIA]
    verificados = dias_completos(balanco, "carga")
    programados = dias_completos(dessem, "demanda")
    print(f"Decisão em {decisao.date()} | balanço completo até {max(verificados).date()} | DESSEM publicado até {max(programados).date()}", flush=True)
    store = Store(DATA_DIR)
    try:
        renovaveis_atual, temperatura_atual = previsao_atual(store, locais, decisao.date().isoformat())
    finally:
        store.close()
    atuais = agregar_previsoes(renovaveis_atual)
    receitas = {1: json.loads((RAIZ / "docs/inventory/carga_liquida_results.json").read_text(encoding="utf-8"))["escolhas"],
                2: json.loads((RAIZ / "docs/inventory/carga_liquida_dmais2_results.json").read_text(encoding="utf-8"))["escolhas"]}
    resultados = []
    for passo in (1, 2):
        alvo = decisao + passo * UM_DIA
        h = horizonte_efetivo(alvo, verificados, programados)
        if h is None:
            print(f"{alvo.date()}: dados insuficientes para os horizontes treinados (D+1, D+2); dia não previsto.")
            continue
        dia = h + 1  # rodada do tempo emitida h+1 dias antes, como no treino
        previsoes = juntar_previsoes(carregar_previsao_renovaveis(dia), atuais)
        arquivada = carregar_temperatura_prevista(dia)
        coluna = "temp_prev_48h" if dia == 2 else "temp_prev"
        temperatura = juntar_temperatura(arquivada, temperatura_atual, coluna)
        pecas = prever_dia(alvo, h, balanco, dessem, previsoes, temperatura, receitas[h])
        resultados.append(pecas.assign(decisao=decisao, alvo=alvo, passo=passo))
        print(f"{alvo.date()} (D+{passo}) previsto com o horizonte treinado D+{h}: receitas {receitas[h]}", flush=True)
    if not resultados:
        return 1
    tabela = pd.concat(resultados, ignore_index=True)
    destino = DATA_DIR / "gold/previsao_operacional.parquet"
    if destino.exists():
        anterior = pd.read_parquet(destino)
        tabela = pd.concat([anterior[anterior["decisao"] != decisao], tabela], ignore_index=True)
    tabela.to_parquet(destino, index=False)
    atual = tabela[tabela["decisao"] == decisao]
    liquida = banda_operacional(atual, receitas, decisao)
    anterior_liq = DATA_DIR / "gold/previsao_operacional_liquida.parquet"
    if anterior_liq.exists():
        velho = pd.read_parquet(anterior_liq)
        liquida_tudo = pd.concat([velho[velho["decisao"] != decisao], liquida], ignore_index=True)
    else:
        liquida_tudo = liquida
    liquida_tudo.to_parquet(anterior_liq, index=False)
    resumo = liquida.groupby(["data", "subsistema"]).agg(media_mw=("previsto", "mean"), minimo_mw=("previsto", "min"), maximo_mw=("previsto", "max"),
                                                        hora_do_maximo=("previsto", lambda s: int(liquida.loc[s.idxmax(), "hora"])),
                                                        banda80_inf_media=("banda_inf", "mean"), banda80_sup_media=("banda_sup", "mean"),
                                                        regua_media_mw=("ons_ant_semana", "mean"), horizonte=("horizonte", "first")).round(0)
    print("\nCarga líquida prevista (MW médios; banda de 80% pelos erros dos 120 dias anteriores do backtest;")
    print("régua = programação de T−1 corrigida por hora e dia da semana):")
    print(resumo.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
