"""Operational net-load forecast: what the desk receives today for tomorrow (D+1) and the day after (D+2).

Uses the same functions as the backtest, with the recipes chosen on 2025 (stored in the results JSON files), training
on everything available at decision time. If an input is not out yet (the D−1 balance comes out around 7:50 pm
Brasília time; the D+1 DESSEM between 3 and 5 pm), the day is forecast with the next horizon, which needs less
information, and this is recorded in the output. Includes the empirical 80% prediction band.
"""
import pandas as pd

from models.renovaveis import backtest_pecas, corrigir_vies, corrigir_vies_semana, referencias_ons

SINAIS = {"carga": 1, "eolica": -1, "solar": -1}
SUBSISTEMAS = 4
UM_DIA = pd.Timedelta(days=1)


def dias_completos(frame, coluna, horas=24):
    """Days on which all 4 subsystems have every hour of `coluna`."""
    f = frame.dropna(subset=[coluna])
    contagem = f.groupby([f["instante"].dt.normalize(), "subsistema"]).size().unstack()
    if contagem.shape[1] < SUBSISTEMAS:
        return set()
    return set(contagem.index[(contagem >= horas).all(axis=1)])


def horizonte_efetivo(alvo, dias_verificados, dias_dessem, maximo=2):
    """Smallest horizon h with verified data for target−(h+1) and the schedule for target−(h−1) already published."""
    ultimo = max(dias_verificados) if dias_verificados else None
    for h in range(1, maximo + 1):
        if ultimo is not None and ultimo >= alvo - (h + 1) * UM_DIA and (alvo - (h - 1) * UM_DIA) in dias_dessem:
            return h
    return None


def estender_balanco(balanco, ate):
    """Append empty hours up to `ate` (exclusive), so the model has somewhere to write the future."""
    partes = [balanco]
    for subsistema, g in balanco.groupby("subsistema"):
        futuras = pd.date_range(g["instante"].max() + pd.Timedelta(hours=1), ate - pd.Timedelta(hours=1), freq="h")
        if len(futuras):
            partes.append(pd.DataFrame({"subsistema": subsistema, "instante": futuras}))
    return pd.concat(partes, ignore_index=True).sort_values(["subsistema", "instante"], ignore_index=True)


def referencias_corrigidas(balanco, dessem, horizonte):
    """ONS schedule and its bias-corrected versions, with errors known only up to the decision."""
    saidas = []
    for subsistema, bal in balanco.groupby("subsistema"):
        d = dessem[dessem["subsistema"] == subsistema].set_index("instante").sort_index().rename(columns={"demanda": "carga"})
        b = bal.set_index("instante").sort_index()
        for peca in SINAIS:
            ref = referencias_ons(d, peca, horizonte)
            real = b[peca].rename("real").reset_index()
            real = real.assign(data=real["instante"].dt.normalize(), hora=real["instante"].dt.hour)[["data", "hora", "real"]]
            g = ref.merge(real, on=["data", "hora"], how="outer").sort_values(["data", "hora"], ignore_index=True)
            g["ons_corrigido"] = corrigir_vies(g).clip(lower=0)
            g["ons_ant_corrigido"] = corrigir_vies(g, coluna="ons_ant", gap=horizonte + 1).clip(lower=0)
            g["ons_ant_semana"] = corrigir_vies_semana(g, coluna="ons_ant", gap=horizonte + 1).clip(lower=0)
            saidas.append(g.drop(columns=["real"]).assign(subsistema=subsistema, peca=peca))
    return pd.concat(saidas, ignore_index=True)


def aplicar_receitas(pecas, escolhas):
    """Blends used by the recipes and the `previsto` column with the model chosen for each component."""
    ml = pecas[["ridge", "gbm"]].mean(axis=1)
    pecas = pecas.assign(media_com_ons=0.5 * ml + 0.5 * pecas["ons"],
                         media_com_ons_corrigido=0.5 * ml + 0.5 * pecas["ons_corrigido"],
                         media_com_ons_ant_corrigido=0.5 * ml + 0.5 * pecas["ons_ant_corrigido"],
                         media_com_ons_ant_semana=0.5 * ml + 0.5 * pecas["ons_ant_semana"])
    pecas["receita"] = pecas["peca"].map(escolhas)
    pecas["previsto"] = float("nan")
    for receita, linhas in pecas.groupby("receita").groups.items():
        pecas.loc[linhas, "previsto"] = pecas.loc[linhas, receita]
    return pecas


def prever_dia(alvo, horizonte, balanco, dessem, previsoes, temperatura, escolhas):
    """Hour-by-hour forecast of `alvo` per subsystem and component, with the horizon's frozen recipe."""
    fim = alvo + UM_DIA
    estendido = estender_balanco(balanco, fim)
    pecas = backtest_pecas(estendido, dessem, previsoes, temperatura, [(alvo, fim)], log=lambda *_: None,
                           horizonte=horizonte, operacional=True)
    refs = referencias_corrigidas(estendido, dessem, horizonte).drop(columns=["ons", "ons_ant"])
    pecas = pecas.merge(refs, on=["subsistema", "peca", "data", "hora"], how="left")
    return aplicar_receitas(pecas, escolhas).assign(horizonte=horizonte)


def historico_liquido(pecas_backtest, escolhas, regua=None):
    """Backtest net load (subsystems and national grid) with the frozen recipe: forecast, actual and, if requested, the benchmark."""
    p = pecas_backtest.copy()
    p["previsto"] = float("nan")
    for peca, receita in escolhas.items():
        p.loc[p["peca"] == peca, "previsto"] = p.loc[p["peca"] == peca, receita]
    liq = carga_liquida(p, "previsto").merge(carga_liquida(p, "real"), on=["subsistema", "data", "hora"], how="outer")
    if regua:
        liq = liq.merge(carga_liquida(p, regua).rename(columns={regua: "regua"}), on=["subsistema", "data", "hora"], how="left")
    return liq.dropna(subset=["previsto", "real"]).reset_index(drop=True)


def quantis_residuo(historico, ate, janela=120, nivel=0.8):
    """Quantiles of the error (forecast − actual) per subsystem and hour over the `janela` days before `ate` (exclusive, 1-day margin).

    It is the limit of a Monte Carlo simulation that resamples past errors: in 2026 the 80% band covered
    79–80% of hours (scripts/diagnostico/residuos_2026.py). `historico`: columns subsistema, data, hora, previsto, real.
    """
    h = historico[(historico["data"] < ate - UM_DIA) & (historico["data"] >= ate - pd.Timedelta(days=janela))]
    erro = (h["previsto"] - h["real"]).rename("erro")
    alfa = (1 - nivel) / 2
    q = erro.groupby([h["subsistema"], h["hora"]]).quantile([alfa, 1 - alfa]).unstack()
    q.columns = ["q_inf", "q_sup"]
    return q.reset_index()


def aplicar_banda(frame, quantis):
    """banda_inf/banda_sup: the actual falls inside with the level's probability (forecast − high error, forecast − low error)."""
    f = frame.merge(quantis, on=["subsistema", "hora"], how="left")
    return f.assign(banda_inf=f["previsto"] - f["q_sup"], banda_sup=f["previsto"] - f["q_inf"]).drop(columns=["q_inf", "q_sup"])


def banda_walk_forward(historico, inicio, janela=120, nivel=0.8):
    """Band for each month from `inicio`, with quantiles from days before that month only (no look-ahead)."""
    partes = []
    for mes in pd.date_range(inicio, historico["data"].max(), freq="MS"):
        alvo = historico[(historico["data"] >= mes) & (historico["data"] < mes + pd.offsets.MonthBegin(1))]
        partes.append(aplicar_banda(alvo, quantis_residuo(historico, mes, janela, nivel)))
    return pd.concat(partes, ignore_index=True)


def carga_liquida(pecas, coluna="previsto"):
    """Net load per subsystem and hour, plus the national sum (only hours with all 4 subsystems)."""
    largura = pecas.pivot_table(index=["subsistema", "data", "hora"], columns="peca", values=coluna, dropna=False).reindex(columns=list(SINAIS))
    liquida = sum(sinal * largura[peca] for peca, sinal in SINAIS.items()).rename(coluna).reset_index()
    sin = liquida.groupby(["data", "hora"]).filter(lambda g: g[coluna].notna().sum() == SUBSISTEMAS)
    sin = sin.groupby(["data", "hora"], as_index=False)[coluna].sum().assign(subsistema="SIN")
    return pd.concat([liquida, sin], ignore_index=True)
