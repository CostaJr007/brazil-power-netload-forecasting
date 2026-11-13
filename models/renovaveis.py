"""Net load by summing components: load − wind − solar, at D+1 and D+2.

Each source is forecast per subsystem and hour with data available on the evening of the decision: verified generation
up to T−gap and weather forecasts issued 48 h (D+1) or 72 h (D+2) before each hour of T. The target is the ratio of
generation to the recent level of the same hour, which already embeds capacity growth, seasonality and the recent
curtailment level. Solar is zero at night by construction.

The benchmark is the ONS DESSEM schedule (D+1) or the previous-day schedule corrected by hour and weekday (D+2).
"""
import numpy as np
import pandas as pd

from models.carga_d1 import CAL, LAGS, TEMP, _gbm, _ridge_por_hora, preparar_d1

GAP = 2
NIVEL_MINIMO = 1.0
RAZAO_MAXIMA = 3.0
LAGS_FONTE = ["r2", "r7", "tend"]


def folds_trimestrais(primeiro_ano, ultimo):
    """Refit every quarter, because archived forecasts only start in 2024."""
    ultimo = pd.Timestamp(ultimo)
    folds = []
    for inicio in pd.date_range(pd.Timestamp(primeiro_ano, 1, 1), ultimo, freq="QS"):
        fim = min(inicio + pd.offsets.QuarterBegin(startingMonth=1), ultimo + pd.Timedelta(days=1))
        folds.append((inicio, fim))
    return folds


def corrigir_vies(g, janela=28, coluna="ons", gap=GAP):
    """`coluna` minus its recent mean error at the same hour, with errors known up to T−gap.

    g: rows of one subsystem and component, with columns data, hora, `coluna` and real. DESSEM has a level bias
    against the balance (Southeast load +1.1 GW in 2026), and a desk would correct it before any ML.
    """
    saida = pd.Series(np.nan, index=g.index)
    for _, h in g.groupby("hora"):
        erro = (h[coluna] - h["real"]).set_axis(h["data"]).asfreq("D")
        vies = erro.shift(gap).rolling(janela, min_periods=7).mean().reindex(h["data"]).to_numpy()
        saida.loc[h.index] = h[coluna].to_numpy() - vies
    return saida


def corrigir_vies_semana(g, coluna="ons_ant", gap=GAP, semanas=4):
    """Like corrigir_vies, but the bias is measured per hour AND weekday (last `semanas` known occurrences).

    At D+2 the available schedule is T−1's: on a Monday it is Sunday's. The systematic error of that day
    switch (Sunday → Monday, Friday → Saturday) only shows up when split by weekday.
    """
    saida = pd.Series(np.nan, index=g.index)
    dia_semana = g["data"].dt.day_of_week
    for _, h in g.groupby([g["hora"], dia_semana]):
        erro = (h[coluna] - h["real"]).set_axis(h["data"]).asfreq("7D")
        # Previous occurrence of the same weekday = 7 days earlier; valid only if 7 ≥ gap (always, up to D+6).
        passos = int(np.ceil(gap / 7))
        vies = erro.shift(passos).rolling(semanas, min_periods=2).mean().reindex(h["data"]).to_numpy()
        saida.loc[h.index] = h[coluna].to_numpy() - vies
    return saida


def preparar_fonte(serie, previsoes, gap=GAP):
    """serie: hourly generation. previsoes: hourly index, one column per forecast variable. Returns date × hour rows.

    gap: most recent day with verified generation (2 for D+1, 3 for D+2). r2 keeps its name but uses lag max(2, gap).
    """
    base = pd.DataFrame({"y": serie}).join(previsoes, how="left")
    base["data"], base["hora"] = base.index.normalize(), base.index.hour
    colunas_prev = list(previsoes.columns)
    recente = max(2, gap)
    partes = []
    for hora, grupo in base.groupby("hora"):
        g = grupo.set_index("data").asfreq("D")
        y = g["y"]
        nivel = y.shift(gap).rolling(28, min_periods=14).mean()
        valido = nivel > NIVEL_MINIMO
        # Ratio capped at 3: at dawn the level is near zero and the ratio explodes, dominating the GBM (which pools hours).
        x = pd.DataFrame({"y": y, "nivel": nivel, "alvo": (y / nivel).where(valido).clip(upper=RAZAO_MAXIMA),
                          "r2": (y.shift(recente) / nivel).where(valido), "r7": (y.shift(max(7, gap)) / nivel).where(valido),
                          "tend": (y.shift(gap).rolling(7, min_periods=4).mean() / nivel).where(valido),
                          "persistencia": y.shift(recente), "media7": y.shift(gap).rolling(7, min_periods=4).mean()}, index=g.index)
        for coluna in colunas_prev:
            # Compare the forecast with earlier (already known) forecasts for the same hour.
            media = g[coluna].shift(1).rolling(28, min_periods=14).mean()
            x[coluna] = g[coluna]
            x[coluna + "_a"] = g[coluna] - media
            x[coluna + "_a2"] = (g[coluna] - media) ** 2
        partes.append(x.assign(hora=hora))
    return pd.concat(partes).rename_axis("data")


def variaveis_previsao(previsoes, fonte):
    colunas = [c for c in previsoes.columns if previsoes[c].notna().mean() > 0.5]
    return [f"{c}{s}" for c in colunas for s in ("", "_a", "_a2")] if fonte != "cidade" else []


def prever_fonte(x, colunas_prev, inicio, fim, operacional=False):
    """Train up to `inicio` and forecast [inicio, fim). Night hours (level ~0) get a zero forecast.

    operacional=True forecasts days whose actual value does not exist yet (production use, not backtest).
    """
    treino = x[(x.index < inicio) & x["alvo"].notna()]
    periodo = (x.index >= inicio) & (x.index < fim) & x["persistencia"].notna()
    teste = x[periodo if operacional else periodo & x["y"].notna()].copy()
    if teste.empty or len(treino) < 500:
        return None
    n = teste["nivel"].fillna(0).to_numpy()
    def voltar(razao):
        return np.where(n > NIVEL_MINIMO, np.clip(razao, 0, None) * n, 0.0)
    teste["ridge_sem_previsao"] = voltar(_ridge_por_hora(treino, teste, LAGS_FONTE, "alvo"))
    teste["ridge"] = voltar(_ridge_por_hora(treino, teste, LAGS_FONTE + colunas_prev, "alvo")) if colunas_prev else teste["ridge_sem_previsao"]
    colunas_gbm = LAGS_FONTE + colunas_prev + ["hora"]
    if len(treino) >= 2000:
        teste["gbm"] = voltar(_gbm(treino, teste.assign(**{c: teste[c] for c in colunas_gbm}), colunas_gbm, "alvo"))
    else:
        teste["gbm"] = teste["ridge"]
    teste["media_ridge_gbm"] = teste[["ridge", "gbm"]].mean(axis=1)
    return teste


SAIDA = ["data", "hora", "real", "persistencia", "media7", "ons", "ons_ant", "ridge_sem_previsao", "ridge", "gbm", "media_ridge_gbm"]


def referencias_ons(d, peca, horizonte):
    """ons: the schedule for day T itself (only exists the day before T).
    ons_ant: the most recent schedule available at decision time, T−(horizonte−1)'s. At D+1 it is the same."""
    serie = d[peca].rename("ons")
    # Union of indexes: at D+2 the schedule for T does not exist yet, but T−1's (ons_ant) does.
    ref = pd.concat([serie, serie.shift(freq=pd.Timedelta(days=horizonte - 1)).rename("ons_ant")], axis=1)
    ref = ref.rename_axis("instante").reset_index()
    return ref.assign(data=ref["instante"].dt.normalize(), hora=ref["instante"].dt.hour)[["data", "hora", "ons", "ons_ant"]]


def backtest_pecas(balanco, dessem, previsoes, temperatura, folds, log=print, horizonte=1, operacional=False):
    """Returns a long table: data, hora, subsistema, peca (carga/eolica/solar), real and each model.

    horizonte: 1 = D+1 (decided the day before), 2 = D+2... Verified data run up to T−(horizonte+1), and
    `previsoes` and `temperatura` must come from the run issued horizonte+1 days before each hour.
    operacional: also forecasts days without an actual value (the balance must have empty rows for them).
    """
    gap = horizonte + 1
    coluna_temp = "temp_prev_48h" if "temp_prev_48h" in temperatura else "temp_prev"
    saidas = []
    for subsistema, bal in balanco.groupby("subsistema"):
        bal = bal.set_index("instante").sort_index()
        d = dessem[dessem["subsistema"] == subsistema].set_index("instante").sort_index()
        pecas = {"eolica": ("eolica", ["eolica"]), "solar": ("solar", ["solar", "cidade"])}
        for peca, (coluna, grupos) in pecas.items():
            prev = pd.DataFrame(index=pd.DatetimeIndex([]))
            for grupo in grupos:
                recorte = previsoes.get((subsistema, grupo))
                if recorte is not None:
                    prev = prev.join(recorte.add_prefix(f"{grupo}_"), how="outer")
            if peca == "eolica":
                prev = prev[[c for c in prev.columns if "vento100" in c]]
            else:
                prev = prev[[c for c in prev.columns if ("radiacao" in c or "nuvens" in c)]]
            x = preparar_fonte(bal[coluna], prev, gap=gap)
            colunas_prev = [f"{c}{s}" for c in prev.columns if prev[c].notna().mean() > 0.4 for s in ("", "_a", "_a2")]
            referencia = referencias_ons(d, peca, horizonte)
            for inicio, fim in folds:
                teste = prever_fonte(x, colunas_prev, inicio, fim, operacional=operacional)
                if teste is None:
                    continue
                unido = teste.reset_index().merge(referencia, on=["data", "hora"], how="left").rename(columns={"y": "real"})
                saidas.append(unido[SAIDA].assign(subsistema=subsistema, peca=peca))
        # Load: same structure as the D+1 load model, now with the balance's load as target.
        temp = (temperatura[temperatura["subsistema"] == ("SECO" if subsistema == "SE" else subsistema)]
                .groupby("instante")[[coluna_temp, "temp_analise"]].mean().rename(columns={coluna_temp: "temp_prev"}))
        x = preparar_d1(bal[["carga"]].assign(programada=np.nan), temp, gap=gap)
        referencia = referencias_ons(d.rename(columns={"demanda": "carga"}), "carga", horizonte)
        colunas = LAGS + CAL + TEMP
        for inicio, fim in folds:
            treino = x[(x.index < inicio) & x["alvo_nivel"].notna()]
            exigidas = ["nivel"] + colunas if operacional else ["carga", "nivel"] + colunas
            teste = x[(x.index >= inicio) & (x.index < fim) & x[exigidas].notna().all(axis=1)].copy()
            if teste.empty:
                continue
            n = teste["nivel"].to_numpy()
            teste["ridge"] = n * np.exp(_ridge_por_hora(treino, teste, colunas, "alvo_nivel"))
            teste["gbm"] = n * np.exp(_gbm(treino, teste, colunas + ["hora"], "alvo_nivel"))
            teste["media_ridge_gbm"] = teste[["ridge", "gbm"]].mean(axis=1)
            teste["ridge_sem_previsao"] = n * np.exp(_ridge_por_hora(treino, teste, LAGS + CAL, "alvo_nivel"))
            teste = teste.reset_index().rename(columns={"carga": "real"}).merge(referencia, on=["data", "hora"], how="left")
            teste["persistencia"], teste["media7"] = teste["nivel"] * teste["r2"], teste["nivel"] * teste["tend"]
            saidas.append(teste[SAIDA].assign(subsistema=subsistema, peca="carga"))
        log(f"Components {subsistema} ok")
    return pd.concat(saidas, ignore_index=True)
