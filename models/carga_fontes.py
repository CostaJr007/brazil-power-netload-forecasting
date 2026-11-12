"""Quanto cada fonte de dados ajuda a antecipar a carga do dia seguinte?

Testa, grupo a grupo, meteorologia observada, reservatórios, geração das usinas e previsão real de
vento, sol e umidade. Dois alvos, ambos emitidos antes da divulgação:
  verificada: a carga que de fato ocorrerá em T;
  programada: o número que o ONS publicará para T.
Todo dado observado entra com defasagem de 2 dias, a mesma da carga verificada.
"""
import numpy as np
import pandas as pd

from models.carga_d1 import CAL, LAGS, TEMP, _gbm, _ridge_por_hora, preparar_d1

P_LAGS = ["p1", "p7", "p14", "tend_p"]
BASES = {"verificada": ("alvo_nivel", "nivel", LAGS), "programada": ("alvo_prog", "nivel_p", P_LAGS)}
COLUNAS_CLIMA = ["temp", "temp_max", "radiacao", "vento", "umidade", "chuva"]
COLUNAS_GERACAO = ["eolica", "solar", "hidraulica", "termica"]
PREVISTAS = ["radiacao_prev", "vento_prev", "umidade_prev", "nuvens_prev"]
CLIMA = [f"{c}_{s}" for c in COLUNAS_CLIMA for s in ("l2", "m7")]
HIDRO = ["ear", "ear_d7", "ena_pct", "ena_m7"]
GERACAO = [f"{c}_{s}" for c in COLUNAS_GERACAO for s in ("l2", "m7")]
PREV_EXTRA = [f"{c}_a" for c in PREVISTAS]
GRUPOS = {"historico": [], "temp_prevista": TEMP, "clima_observado": CLIMA, "reservatorios": HIDRO, "geracao": GERACAO,
          "tudo": TEMP + CLIMA + HIDRO + GERACAO}
GRUPOS_PREVISAO = {"historico": [], "temp_prevista": TEMP, "vento_sol_previstos": PREV_EXTRA, "temp_vento_sol_previstos": TEMP + PREV_EXTRA}


def variaveis_diarias(extras):
    """extras: índice diário com clima, ear, ena_pct e geração. Nada posterior a T−2 sai daqui."""
    x = pd.DataFrame(index=extras.index)
    for coluna in COLUNAS_CLIMA:
        passado = extras[coluna].shift(2)
        media = passado.rolling(30, min_periods=20).mean()
        x[coluna + "_l2"], x[coluna + "_m7"] = passado - media, passado.rolling(7, min_periods=5).mean() - media
    for coluna in COLUNAS_GERACAO:
        passado = extras[coluna].shift(2)
        media = passado.rolling(28, min_periods=20).mean().replace(0, np.nan)
        x[coluna + "_l2"], x[coluna + "_m7"] = passado / media, passado.rolling(7, min_periods=5).mean() / media
    ear = extras["ear"].shift(2)
    x["ear"], x["ear_d7"] = ear, ear - ear.shift(7)
    ena = extras["ena_pct"].shift(2)
    x["ena_pct"], x["ena_m7"] = ena, ena.rolling(7, min_periods=5).mean()
    return x


def adicionar_programada(x):
    """Variáveis para prever a programada de T: as programadas até T−1 já foram publicadas."""
    partes = []
    for hora, g in x.groupby("hora"):
        p = g["programada"]
        nivel = p.shift(1).rolling(28, min_periods=21).mean()
        partes.append(g.assign(nivel_p=nivel, alvo_prog=np.log(p / nivel), p1=p.shift(1) / nivel, p7=p.shift(7) / nivel,
                               p14=p.shift(14) / nivel, tend_p=p.shift(1).rolling(7, min_periods=5).mean() / nivel))
    return pd.concat(partes)


def adicionar_previstas(x, previstas):
    """previstas: índice horário. Anomalia contra a média de 30 dias anteriores, na mesma hora."""
    if previstas is None or previstas.empty:
        return x.assign(**{c: np.nan for c in PREV_EXTRA})
    base = previstas.assign(data=previstas.index.normalize(), hora=previstas.index.hour)
    partes = []
    for hora, g in base.groupby("hora"):
        g = g.set_index("data").asfreq("D")
        saida = pd.DataFrame(index=g.index)
        for coluna in PREVISTAS:
            saida[coluna + "_a"] = g[coluna] - g[coluna].shift(1).rolling(30, min_periods=20).mean()
        partes.append(saida.assign(hora=hora))
    return x.reset_index().merge(pd.concat(partes).rename_axis("data").reset_index(), on=["data", "hora"], how="left").set_index("data")


def backtest_fontes(carga, temperatura, extras, previstas, folds, log=print):
    """Devolve previsões longas: subsistema × data × hora × alvo × modelo."""
    saidas = []
    for subsistema, grupo in carga.groupby("subsistema"):
        temp = (temperatura[temperatura["subsistema"] == subsistema].groupby("instante")[["temp_prev_48h", "temp_analise"]].mean()
                .rename(columns={"temp_prev_48h": "temp_prev"}))
        x = adicionar_programada(preparar_d1(grupo.set_index("instante")[["carga", "programada"]], temp))
        x = x.join(variaveis_diarias(extras[subsistema]), on="data")
        extra_h = previstas[previstas["subsistema"] == subsistema].groupby("instante")[PREVISTAS].mean() if previstas is not None else None
        x = adicionar_previstas(x, extra_h)
        for inicio, fim in folds:
            treino = x[x.index < inicio]
            teste_base = x[(x.index >= inicio) & (x.index < fim)]
            for alvo_nome, (alvo, nivel, lags) in BASES.items():
                real = {"verificada": "carga", "programada": "programada"}[alvo_nome]
                teste = teste_base[teste_base[[real, nivel] + lags + TEMP].notna().all(axis=1)].copy()
                if teste.empty:
                    continue
                tr = treino[treino[alvo].notna()]
                saida = teste[["hora", real]].rename(columns={real: "real"}).assign(subsistema=subsistema, ano=inicio.year, alvo=alvo_nome)
                n = teste[nivel].to_numpy()
                for nome, grupo_colunas in GRUPOS.items():
                    colunas = lags + CAL + grupo_colunas
                    saida["ridge_" + nome] = n * np.exp(_ridge_por_hora(tr, teste, colunas, alvo))
                for nome in ("historico", "tudo"):
                    colunas = lags + CAL + GRUPOS[nome] + ["hora"]
                    saida["gbm_" + nome] = n * np.exp(_gbm(tr, teste, colunas, alvo))
                # Vento/sol/umidade previstos só existem desde 2024: teste à parte, com treino a partir daí.
                recente = tr[tr.index >= pd.Timestamp("2024-02-01")]
                if inicio.year >= 2025 and previstas is not None:
                    for nome, grupo_colunas in GRUPOS_PREVISAO.items():
                        saida["recente_" + nome] = n * np.exp(_ridge_por_hora(recente, teste, lags + CAL + grupo_colunas, alvo))
                saidas.append(saida.reset_index())
            log(f"Fontes {subsistema} {inicio.year}")
    return pd.concat(saidas, ignore_index=True)
