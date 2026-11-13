"""Slicing the D+1 load model by time of year to see where it does well or badly.

Two different ideas:
  1. Evaluate in slices: one model, with error measured by season, month and hour band.
  2. Train in slices: one Ridge per hour that learns only from its own season or neighbouring months. It helps if the
     temperature response changes through the year, at the cost of fewer examples.
"""
import numpy as np
import pandas as pd

from models.carga_d1 import CAL, GAP, LAGS, TEMP, _ridge_por_hora, preparar_d1
from models.validation import train_cutoff

ESTACOES = {12: "verao", 1: "verao", 2: "verao", 3: "outono", 4: "outono", 5: "outono",
            6: "inverno", 7: "inverno", 8: "inverno", 9: "primavera", 10: "primavera", 11: "primavera"}
COLUNAS = LAGS + CAL + TEMP


def faixa_horaria(hora):
    if hora <= 5:
        return "madrugada_00_05"
    if hora <= 9:
        return "manha_06_09"
    if hora <= 15:
        return "sol_10_15"
    if hora <= 21:
        return "ponta_16_21"
    return "noite_22_23"


def _por_fatia(treino, teste, fatias_treino, fatias_teste, colunas):
    """Train one model per slice present in the test set. Each test slice says which labels it trains on."""
    saida = np.full(len(teste), np.nan)
    for rotulo in pd.unique(fatias_teste):
        marca = np.asarray(fatias_teste == rotulo)
        aceitos = rotulo if isinstance(rotulo, tuple) else (rotulo,)
        recorte = treino[np.isin(fatias_treino, aceitos)]
        saida[marca] = _ridge_por_hora(recorte, teste[marca], colunas, "alvo_nivel")
    return saida


def backtest_sazonal(carga, temperatura, folds, log=print):
    resultados = []
    for subsistema, grupo in carga.groupby("subsistema"):
        temp = (temperatura[temperatura["subsistema"] == subsistema].groupby("instante")[["temp_prev_48h", "temp_analise"]].mean()
                .rename(columns={"temp_prev_48h": "temp_prev"}))
        x = preparar_d1(grupo.set_index("instante")[["carga", "programada"]], temp)
        for inicio, fim in folds:
            treino = x[x.index < train_cutoff(inicio, GAP)]
            exigidas = ["carga", "programada", "nivel", "e_m28", "t_prev"] + COLUNAS
            teste = x[(x.index >= inicio) & (x.index < fim) & x[exigidas].notna().all(axis=1)].copy()
            if teste.empty:
                continue
            n = teste["nivel"].to_numpy()
            teste["ons"] = teste["programada"]
            teste["ons_vies28"] = teste["programada"] * (1 + teste["e_m28"])
            teste["global"] = n * np.exp(_ridge_por_hora(treino, teste, COLUNAS, "alvo_nivel"))
            est_tr, est_te = treino.index.month.map(ESTACOES).to_numpy(), teste.index.month.map(ESTACOES).to_numpy()
            teste["por_estacao"] = n * np.exp(_por_fatia(treino, teste, est_tr, est_te, COLUNAS))
            mes_tr, mes_te = treino.index.month.to_numpy(), teste.index.month.to_numpy()
            # Target month plus its two neighbours: a moving 3-month window, so as not to lose too many examples.
            vizinhos = np.array([tuple(((m + d - 1) % 12) + 1 for d in (-1, 0, 1)) for m in mes_te], dtype=object)
            saida = np.full(len(teste), np.nan)
            for m in np.unique(mes_te):
                marca = mes_te == m
                recorte = treino[np.isin(mes_tr, vizinhos[marca][0])]
                saida[marca] = _ridge_por_hora(recorte, teste[marca], COLUNAS, "alvo_nivel")
            teste["por_mes_janela"] = n * np.exp(saida)
            teste["subsistema"], teste["ano"] = subsistema, inicio.year
            resultados.append(teste.reset_index())
            log(f"Seasonal {subsistema} {inicio.year}: {len(teste)} hours")
    saida = pd.concat(resultados, ignore_index=True)
    saida["estacao"] = saida["data"].dt.month.map(ESTACOES)
    saida["mes"] = saida["data"].dt.month
    saida["faixa"] = saida["hora"].map(faixa_horaria)
    saida["tipo_dia"] = np.select([saida["feriado"] == 1, saida["data"].dt.dayofweek >= 5], ["feriado", "fim_de_semana"], "dia_util")
    return saida
