"""Calendário e temperatura → carga diária do dia T, emitida na manhã de T−1.

O dado mais recente da verificada na emissão é o de T−2 (GAP). O alvo é a razão
carga/média dos 28 dias anteriores à emissão, porque árvores não extrapolam tendência.
Modelos:
  naive           carga de T−7 (mesmo dia da semana)
  ons             carga programada do ONS: o concorrente a bater
  ons_vies28      programada corrigida pelo erro médio recente (baseline de viés)
  gbm_calendario  lags + calendário
  gbm_temp        + temperatura observada até T−2 (disponível de verdade)
  gbm_cenario     + temperatura do próprio dia T (previsão perfeita: limite superior)
  ons_corrigido   aprende o viés do ONS: programada × correção por erros passados e calendário
"""
from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from models.dados import ESTADOS_SUBSISTEMA, feriados_nacionais
from models.validation import placebo_shift

GAP = 2
CALENDARIO = ["dia_semana", "mes", "sen", "cos", "feriado", "vespera", "pos_feriado", "ponte"]
LAGS = ["r2", "r3", "r7", "r14", "tend"]
ERROS_ONS = ["e2", "e3", "e7", "e14", "e_media7", "e_media28", "programada_rel"]


def calendario(datas):
    indice = pd.DatetimeIndex(datas)
    feriados = {f for ano in range(indice.year.min() - 1, indice.year.max() + 2) for f in feriados_nacionais(ano)}
    marca = lambda delta: np.array([(d.date() + timedelta(days=delta)) in feriados for d in indice], dtype=int)  # noqa: E731
    t = 2 * np.pi * indice.day_of_year.to_numpy() / 365.25
    dow = indice.day_of_week.to_numpy()
    feriado, vespera, pos = marca(0), marca(1), marca(-1)
    # Ponte: segunda antes de feriado na terça ou sexta depois de feriado na quinta.
    ponte = ((dow == 0) & (vespera == 1)) | ((dow == 4) & (pos == 1))
    return pd.DataFrame({"dia_semana": dow, "mes": indice.month, "sen": np.sin(t), "cos": np.cos(t),
                         "feriado": feriado, "vespera": vespera, "pos_feriado": pos, "ponte": ponte.astype(int)}, index=indice)


def preparar_subsistema(serie, temperatura, placebo=False):
    """serie: índice diário com carga e programada. temperatura: colunas tmed_UF/tmax_UF."""
    carga = serie["carga"]
    # Média móvel terminando em T−2: nada de T−1 ou T entra aqui.
    nivel = carga.shift(GAP).rolling(28, min_periods=21).mean()
    x = calendario(serie.index)
    x["nivel"], x["carga"], x["programada"] = nivel, carga, serie["programada"]
    x["alvo"] = carga / nivel
    x["naive"] = carga.shift(7)
    for lag in (2, 3, 7, 14):
        x[f"r{lag}"] = carga.shift(lag) / nivel
    x["tend"] = carga.shift(GAP).rolling(7).mean() / nivel
    # Erros passados do ONS: só dias com a verificada já publicada (T−2 para trás).
    erro = carga / serie["programada"] - 1
    for lag in (2, 3, 7, 14):
        x[f"e{lag}"] = erro.shift(lag)
    x["e_media7"], x["e_media28"] = erro.shift(GAP).rolling(7, min_periods=5).mean(), erro.shift(GAP).rolling(28, min_periods=20).mean()
    x["programada_rel"] = serie["programada"] / nivel
    x["alvo_ons"] = carga / serie["programada"]
    temp = temperatura.reindex(serie.index)
    if placebo:
        temp = temp.apply(placebo_shift)
    passada, cenario = {}, {}
    for coluna in temp.columns:
        passada[coluna + "_p2"] = temp[coluna].shift(GAP)
        passada[coluna + "_m7"] = temp[coluna].shift(GAP).rolling(7, min_periods=5).mean()
        cenario[coluna + "_t"] = temp[coluna]
    x = x.join(pd.DataFrame(passada)).join(pd.DataFrame(cenario))
    return x, list(passada), list(cenario)


def _gbm():
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.04, max_leaf_nodes=15, min_samples_leaf=15,
                                         l2_regularization=1.0, random_state=0)


def backtest_carga(carga, temperatura, folds, log=print):
    """Walk-forward anual por subsistema."""
    resultados = []
    for subsistema, grupo in carga.groupby("subsistema"):
        serie = grupo.set_index("data").asfreq("D")[["carga", "programada"]]
        ufs = temperatura[temperatura["uf"].isin(ESTADOS_SUBSISTEMA[subsistema])]
        temp = ufs.pivot(index="data", columns="uf", values=["tmed", "tmax"])
        temp.columns = [f"{m}_{uf}" for m, uf in temp.columns]
        x, passada, cenario = preparar_subsistema(serie, temp)
        x_placebo, _, _ = preparar_subsistema(serie, temp, placebo=True)
        for inicio, fim in folds:
            base = x["alvo"].notna() & x["nivel"].notna()
            treino_m = base & (x.index < inicio)
            teste_m = base & (x.index >= inicio) & (x.index < fim) & x["naive"].notna() & x["programada"].notna()
            # Compara só dias em que todos os modelos têm dado.
            teste_m &= x[cenario].notna().any(axis=1)
            teste = x[teste_m].copy()
            if teste.empty:
                continue
            especificacoes = {"gbm_calendario": (LAGS + CALENDARIO, x), "gbm_temp": (LAGS + CALENDARIO + passada, x),
                              "gbm_cenario": (LAGS + CALENDARIO + passada + cenario, x),
                              "gbm_cenario_placebo": (LAGS + CALENDARIO + passada + cenario, x_placebo)}
            for nome, (colunas, origem) in especificacoes.items():
                modelo = _gbm().fit(origem.loc[treino_m, colunas], origem.loc[treino_m, "alvo"])
                teste[nome] = teste["nivel"] * modelo.predict(origem.loc[teste_m, colunas])
            teste["ons"] = teste["programada"]
            # Baseline trivial: programada corrigida pelo erro médio dos últimos 28 dias conhecidos.
            # Um modelo só tem mérito próprio se ganhar disto, não apenas da programada crua.
            teste["ons_vies28"] = teste["programada"] * (1 + teste["e_media28"])
            # Correção do ONS: treina só onde a programada existia antes do ano de teste.
            treino_ons = treino_m & x["alvo_ons"].notna()
            colunas_ons = ERROS_ONS + CALENDARIO + passada
            if treino_ons.sum() >= 200:
                modelo = _gbm().fit(x.loc[treino_ons, colunas_ons], x.loc[treino_ons, "alvo_ons"])
                teste["ons_corrigido"] = teste["programada"] * modelo.predict(x.loc[teste_m, colunas_ons])
                modelo = _gbm().fit(x.loc[treino_ons, colunas_ons + cenario], x.loc[treino_ons, "alvo_ons"])
                teste["ons_corrigido_cenario"] = teste["programada"] * modelo.predict(x.loc[teste_m, colunas_ons + cenario])
            else:
                teste["ons_corrigido"] = teste["ons_corrigido_cenario"] = np.nan
            teste["subsistema"], teste["ano"] = subsistema, inicio.year
            colunas_saida = ["subsistema", "ano", "carga", "naive", "ons", "ons_vies28", "ons_corrigido", "ons_corrigido_cenario",
                             "gbm_calendario", "gbm_temp", "gbm_cenario", "gbm_cenario_placebo", "feriado"]
            resultados.append(teste[colunas_saida].rename_axis("data").reset_index())
            log(f"Carga {subsistema} {inicio.year}: {len(teste)} dias")
    return pd.concat(resultados, ignore_index=True)
