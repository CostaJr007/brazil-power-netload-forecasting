"""Weather and basins → inflow (ENA), h days ahead.

The target is the ANOMALY: a = ENA/mean − climatology(day of year). Mean and climatology use only each test year's
training data. Three feature families:
  - basin memory: anomalies up to t;
  - observed rain up to t (MERGE): already fallen, not yet turned into flow;
  - rain from t+1 to t+h: a perfect-foresight SCENARIO showing the upper bound of the gain from rain forecasts.

Timing: t is the last day with observed ENA. ONS publishes daily ENA the next morning, so a forecast "h days ahead"
is issued on t+1 and its effective lead time is h−1 days (h=1 is a same-day nowcast). Training only uses targets
dated up to t, i.e. known when the first target of the fold is forecast.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

from models.timeseries import ar_coefficient, kalman_regression, ou_half_life
from models.validation import placebo_shift

HORIZONTES = (1, 3, 7, 14)
MEMORIA = ["a0", "a1", "a2", "a7", "a30"]
CHUVA_PASSADA = ["r1", "r3", "r7", "r15", "r30"]
CENARIO = ["futura_total", "futura_final"]
SAZONAL = ["sen", "cos"]
HARMONICOS = 3
MIN_DIAS_TREINO = 1000


def harmonicos(datas):
    """Sines and cosines of the day of year: a smooth climatology without the noise of per-day means."""
    t = 2 * np.pi * pd.DatetimeIndex(datas).day_of_year.to_numpy() / 365.25
    return np.column_stack([np.ones(len(t))] + [f(k * t) for k in range(1, HARMONICOS + 1) for f in (np.sin, np.cos)])


def preparar_bacia(serie, inicio_teste, h, placebo=False):
    """Features for one basin. serie: daily index with columns ena and chuva. Only training data define the scales.

    The first target of the fold (inicio_teste) is forecast from day inicio_teste−h, so only data up to that day count.
    """
    treino = serie[serie.index <= inicio_teste - pd.Timedelta(days=h)]
    media = treino["ena"].mean()
    # Days without data are left out of the fit: a single NaN would contaminate every coefficient.
    observado = treino["ena"].notna().to_numpy()
    beta = np.linalg.lstsq(harmonicos(treino.index[observado]), (treino["ena"] / media).to_numpy()[observado], rcond=None)[0]
    clima = pd.Series(harmonicos(serie.index) @ beta, index=serie.index)
    chuva_media = treino["chuva"].mean()
    chuva = (placebo_shift(serie["chuva"]) if placebo else serie["chuva"]) / chuva_media
    a = serie["ena"] / media - clima
    alvo_clima = clima.shift(-h)
    x = pd.DataFrame({"a0": a, "a1": a.shift(1), "a2": a.shift(2),
                      "a7": a.rolling(7, min_periods=5).mean(), "a30": a.rolling(30, min_periods=20).mean(),
                      "r1": chuva, "r3": chuva.rolling(3).mean(), "r7": chuva.rolling(7).mean(),
                      "r15": chuva.rolling(15).mean(), "r30": chuva.rolling(30).mean(),
                      # Rain between issue time (exclusive) and the target: what a perfect forecast would provide.
                      "futura_total": chuva.rolling(h).mean().shift(-h),
                      "futura_final": chuva.rolling(min(3, h)).mean().shift(-h)}, index=serie.index)
    t = 2 * np.pi * x.index.day_of_year.to_numpy() / 365.25
    x["sen"], x["cos"] = np.sin(t), np.cos(t)
    x["y"], x["y_alvo"], x["alvo"] = serie["ena"], serie["ena"].shift(-h), a.shift(-h)
    x["clima_alvo"], x["media"] = alvo_clima, media
    x["data_alvo"] = x.index + pd.Timedelta(days=h)
    return x


def backtest_ena(painel, folds, horizontes=HORIZONTES, log=print):
    """Yearly walk-forward. Returns the forecasts (row = basin × target × horizon) and the OU half-lives."""
    series = {b: g.set_index("data").asfreq("D")[["ena", "chuva"]] for b, g in painel.groupby("bacia")}
    resultados, meias_vidas = [], []
    for inicio, fim in folds:
        for h in horizontes:
            partes, placebos = [], []
            for codigo, (bacia, serie) in enumerate(sorted(series.items())):
                if serie[serie.index < inicio]["ena"].count() < MIN_DIAS_TREINO:
                    continue
                for destino, usar_placebo in ((partes, False), (placebos, True)):
                    x = preparar_bacia(serie, inicio, h, usar_placebo)
                    x["bacia"], x["codigo"] = bacia, codigo
                    destino.append(x)
            dados, dados_placebo = pd.concat(partes), pd.concat(placebos)
            base = dados["a0"].notna() & dados["alvo"].notna()
            # Targets known on the issue day of the fold's first target (inicio − h): no fold-boundary leakage.
            corte = inicio - pd.Timedelta(days=h)
            treino_m = base & (dados["data_alvo"] <= corte)
            teste_m = base & (dados["data_alvo"] >= inicio) & (dados["data_alvo"] < fim)
            teste = dados[teste_m].copy()
            desfazer = lambda a, d: d["media"].to_numpy() * (d["clima_alvo"].to_numpy() + a)  # noqa: E731
            teste["persistencia"] = teste["y"]
            teste["climatologia"] = teste["media"] * teste["clima_alvo"]

            # Per-basin models: OU (memory only), Ridge ARX and Kalman ARX.
            ou, ridge, kalman = {}, {}, {}
            for bacia, grupo in dados.groupby("bacia"):
                valido = grupo["a0"].notna() & grupo["alvo"].notna()
                tr = grupo[valido & (grupo["data_alvo"] <= corte)]
                te = grupo[valido & (grupo["data_alvo"] >= inicio) & (grupo["data_alvo"] < fim)]
                if te.empty or tr.empty:
                    continue
                phi = ar_coefficient(tr["a0"], tr["alvo"])
                ou.update(zip(te.index.map(lambda d: (bacia, d)), phi * te["a0"].to_numpy()))
                meias_vidas.append({"ano": inicio.year, "h": h, "bacia": bacia, "phi": phi, "meia_vida": ou_half_life(phi, h)})
                colunas = MEMORIA + CHUVA_PASSADA
                ok = tr[colunas].notna().all(axis=1)
                modelo = Ridge(alpha=1.0).fit(tr.loc[ok, colunas], tr.loc[ok, "alvo"])
                residuo = float(np.var(tr.loc[ok, "alvo"] - modelo.predict(tr.loc[ok, colunas])))
                ok_te = te[colunas].notna().all(axis=1)
                ridge.update(zip(te.index[ok_te].map(lambda d: (bacia, d)), modelo.predict(te.loc[ok_te, colunas])))
                # Kalman runs to the end of the fold: the target of t is only used after t+h.
                ate = grupo[grupo["data_alvo"] < fim]
                matriz = np.column_stack([np.ones(len(ate)), ate["a0"], ate["a7"], ate["r7"]])
                previsto, _ = kalman_regression(matriz, ate["alvo"].to_numpy(), h, residuo)
                mapa = pd.Series(previsto, index=ate.index)
                kalman.update(zip(te.index.map(lambda d: (bacia, d)), mapa.reindex(te.index).to_numpy()))

            chaves = list(zip(teste["bacia"], teste.index))
            for nome, mapa in (("ou", ou), ("ridge_arx", ridge), ("kalman_arx", kalman)):
                teste[nome] = desfazer(np.array([mapa.get(c, np.nan) for c in chaves], dtype=float), teste)

            # Same per-basin regression for each feature set, to isolate the value of rain.
            ridges = {"ridge_memoria": (MEMORIA, dados),
                      "ridge_cenario": (MEMORIA + CHUVA_PASSADA + CENARIO, dados),
                      "ridge_chuva_placebo": (MEMORIA + CHUVA_PASSADA, dados_placebo),
                      "ridge_cenario_placebo": (MEMORIA + CHUVA_PASSADA + CENARIO, dados_placebo)}
            for nome, (colunas, origem) in ridges.items():
                tr, te = origem[treino_m.to_numpy()], origem[teste_m.to_numpy()]
                saida, bacias_teste = np.full(len(te), np.nan), te["bacia"].to_numpy()
                for bacia, grupo in tr.groupby("bacia"):
                    ok = grupo[colunas].notna().all(axis=1)
                    if ok.sum() < 200:
                        continue
                    modelo = Ridge(alpha=1.0).fit(grupo.loc[ok, colunas], grupo.loc[ok, "alvo"])
                    posicoes = np.flatnonzero(bacias_teste == bacia)
                    matriz = te.iloc[posicoes][colunas]
                    valido = matriz.notna().all(axis=1).to_numpy()
                    saida[posicoes[valido]] = modelo.predict(matriz[valido])
                teste[nome] = desfazer(saida, teste)

            # Boosting with all basins pooled: each basin lends its pattern to the others.
            conjuntos = {"gbm_memoria": (MEMORIA + SAZONAL + ["codigo"], dados),
                         "gbm_chuva": (MEMORIA + CHUVA_PASSADA + SAZONAL + ["codigo"], dados),
                         "gbm_cenario": (MEMORIA + CHUVA_PASSADA + CENARIO + SAZONAL + ["codigo"], dados),
                         "gbm_chuva_placebo": (MEMORIA + CHUVA_PASSADA + SAZONAL + ["codigo"], dados_placebo),
                         "gbm_cenario_placebo": (MEMORIA + CHUVA_PASSADA + CENARIO + SAZONAL + ["codigo"], dados_placebo)}
            for nome, (colunas, origem) in conjuntos.items():
                tr = origem[treino_m.to_numpy()]
                te = origem[teste_m.to_numpy()]
                modelo = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.05, max_leaf_nodes=31,
                                                       min_samples_leaf=60, l2_regularization=1.0, random_state=0)
                modelo.fit(tr[colunas], tr["alvo"])
                teste[nome] = desfazer(modelo.predict(te[colunas]), teste)
            teste["h"], teste["ano"] = h, inicio.year
            resultados.append(teste.reset_index(drop=True))
            log(f"ENA {inicio.year} h={h}: {len(teste)} forecasts")
    return pd.concat(resultados, ignore_index=True), pd.DataFrame(meias_vidas)
