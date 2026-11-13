"""Hourly next-day (D+1) load forecast, using temperature actually forecast the day before.

Information available when forecasting day T (evening of T−1):
  - verified load up to T−2;
  - the ONS schedule for T;
  - temperature forecast 48 h before each hour of T.

Two model families:
  "with ONS": learns log(load / schedule), i.e. where ONS errs.
  "without ONS": learns log(load / recent level), useful before ONS publishes its schedule.
The ratio target avoids extrapolating load growth.

One Ridge per hour of the day is common practice in D+1 forecasting: each hour has its own response to temperature.
Temperature columns with the _o suffix are perfect foresight (theoretical bound).
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from models.carga import calendario

GAP = 2
CAL = ["feriado", "vespera", "pos_feriado", "ponte", "sen", "cos"] + [f"dia_{i}" for i in range(6)]
ERROS = ["e2", "e3", "e7", "e14", "e_m7", "e_m28"]
LAGS = ["r2", "r7", "r14", "tend"]
TEMP = ["t_anom", "t_anom2", "t_cdd", "t_hdd"]
TEMP_O = [c + "_o" for c in TEMP]


def _temperatura(serie, sufixo):
    """Temperature terms for one hour of the day. The 30-day mean uses only days before T."""
    media = serie.shift(1).rolling(30, min_periods=20).mean()
    anomalia = serie - media
    return {"t_anom" + sufixo: anomalia, "t_anom2" + sufixo: anomalia ** 2,
            "t_cdd" + sufixo: (serie - 24).clip(lower=0), "t_hdd" + sufixo: (18 - serie).clip(lower=0)}


def preparar_d1(carga, temperatura, gap=GAP):
    """carga: hourly index, columns carga and programada. temperatura: hourly index, columns temp_prev and temp_analise.

    gap: most recent day with verified load, counted back from T (2 for D+1, 3 for D+2...).
    Names r2, e2, e3 keep the nominal lag; with a larger gap the effective lag is max(nominal, gap).
    """
    base = carga.join(temperatura, how="left")
    base["data"], base["hora"] = base.index.normalize(), base.index.hour
    partes = []

    def lag(k):
        return max(k, gap)

    for hora, grupo in base.groupby("hora"):
        g = grupo.set_index("data").asfreq("D")
        c, p = g["carga"], g["programada"]
        # The T−1 error is not known yet: everything here starts at T−gap.
        nivel = c.shift(gap).rolling(28, min_periods=21).mean()
        erro = c / p - 1
        x = pd.DataFrame({"carga": c, "programada": p, "nivel": nivel,
                          "alvo_ons": np.log(c / p), "alvo_nivel": np.log(c / nivel),
                          "r2": c.shift(lag(2)) / nivel, "r7": c.shift(lag(7)) / nivel, "r14": c.shift(lag(14)) / nivel,
                          "tend": c.shift(gap).rolling(7, min_periods=5).mean() / nivel,
                          "e2": erro.shift(lag(2)), "e3": erro.shift(lag(3)), "e7": erro.shift(lag(7)), "e14": erro.shift(lag(14)),
                          "e_m7": erro.shift(gap).rolling(7, min_periods=5).mean(),
                          "e_m28": erro.shift(gap).rolling(28, min_periods=20).mean()}, index=g.index)
        x = x.assign(**_temperatura(g["temp_prev"], ""), **_temperatura(g["temp_analise"], "_o"))
        x["t_prev"], x["hora"] = g["temp_prev"], hora
        partes.append(x)
    x = pd.concat(partes).rename_axis("data")
    cal = calendario(pd.DatetimeIndex(x.index.unique()))
    cal = cal.assign(**{f"dia_{i}": (cal["dia_semana"] == i).astype(int) for i in range(6)})[CAL]
    return x.join(cal, on="data")


def _ridge_por_hora(treino, teste, colunas, alvo):
    saida = pd.Series(np.nan, index=teste.index, dtype=float)
    for hora, tr in treino.groupby("hora"):
        ok = tr[colunas + [alvo]].notna().all(axis=1)
        marca = teste["hora"].to_numpy() == hora
        if ok.sum() < 60 or not marca.any():
            continue
        modelo = make_pipeline(StandardScaler(), Ridge(alpha=10.0)).fit(tr.loc[ok, colunas], tr.loc[ok, alvo])
        matriz = teste.loc[marca, colunas]
        completa = matriz.notna().all(axis=1).to_numpy()
        previsto = np.full(len(matriz), np.nan)
        if completa.any():
            previsto[completa] = modelo.predict(matriz[completa])
        saida[marca] = previsto
    return saida.to_numpy()


def _gbm(treino, teste, colunas, alvo):
    ok = treino[alvo].notna()
    modelo = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=40,
                                           l2_regularization=1.0, random_state=0)
    return modelo.fit(treino.loc[ok, colunas], treino.loc[ok, alvo]).predict(teste[colunas])


def backtest_d1(carga, temperatura, folds, log=print):
    """Yearly walk-forward per subsystem. Returns one row per subsystem × hour × day."""
    resultados = []
    for subsistema, grupo in carga.groupby("subsistema"):
        temp = (temperatura[temperatura["subsistema"] == subsistema].groupby("instante")[["temp_prev_48h", "temp_analise"]].mean()
                .rename(columns={"temp_prev_48h": "temp_prev"}))
        x = preparar_d1(grupo.set_index("instante")[["carga", "programada"]], temp)
        for inicio, fim in folds:
            datas = x.index
            treino = x[(datas < inicio) & x["programada"].notna()]
            exigidas = ["carga", "programada", "nivel", "e_m28", "t_prev"]
            teste = x[(datas >= inicio) & (datas < fim) & x[exigidas].notna().all(axis=1)].copy()
            if teste.empty or treino.empty:
                continue
            p, n = teste["programada"].to_numpy(), teste["nivel"].to_numpy()
            teste["ons"] = p
            teste["ons_vies28"] = p * (1 + teste["e_m28"].to_numpy())
            teste["ridge_ons_sem_temp"] = p * np.exp(_ridge_por_hora(treino, teste, ERROS + CAL, "alvo_ons"))
            teste["ridge_ons"] = p * np.exp(_ridge_por_hora(treino, teste, ERROS + CAL + TEMP, "alvo_ons"))
            teste["ridge_ons_limite"] = p * np.exp(_ridge_por_hora(treino, teste, ERROS + CAL + TEMP_O, "alvo_ons"))
            teste["gbm_ons"] = p * np.exp(_gbm(treino, teste, ERROS + CAL + TEMP + ["hora"], "alvo_ons"))
            teste["combinado"] = teste[["ons_vies28", "ridge_ons", "gbm_ons"]].mean(axis=1, skipna=False)
            teste["ridge_sem_ons"] = n * np.exp(_ridge_por_hora(treino, teste, LAGS + CAL + TEMP, "alvo_nivel"))
            teste["gbm_sem_ons"] = n * np.exp(_gbm(treino, teste, LAGS + CAL + TEMP + ["hora"], "alvo_nivel"))
            teste["subsistema"], teste["ano"] = subsistema, inicio.year
            resultados.append(teste.reset_index())
            log(f"D+1 {subsistema} {inicio.year}: {len(teste)} hours")
    return pd.concat(resultados, ignore_index=True)
