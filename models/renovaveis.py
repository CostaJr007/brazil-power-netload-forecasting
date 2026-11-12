"""Carga líquida de D+1 pela soma das peças: carga − eólica − solar.

Cada fonte é prevista por subsistema e hora, com dados disponíveis na noite de T−1:
geração verificada até T−2 e previsões de tempo emitidas 48 h antes de cada hora de T.
O alvo é a razão entre a geração e o nível recente da mesma hora, que já embute o crescimento
de capacidade, a sazonalidade e o patamar recente de cortes. À noite a solar é zero por construção.

A referência é o DESSEM do ONS, a programação publicada na véspera.
"""
import numpy as np
import pandas as pd

from models.carga_d1 import CAL, LAGS, TEMP, _gbm, _ridge_por_hora, preparar_d1

GAP = 2
NIVEL_MINIMO = 1.0
RAZAO_MAXIMA = 3.0
LAGS_FONTE = ["r2", "r7", "tend"]


def folds_trimestrais(primeiro_ano, ultimo):
    """Retreina a cada trimestre, porque as previsões arquivadas só começam em 2024."""
    ultimo = pd.Timestamp(ultimo)
    folds = []
    for inicio in pd.date_range(pd.Timestamp(primeiro_ano, 1, 1), ultimo, freq="QS"):
        fim = min(inicio + pd.offsets.QuarterBegin(startingMonth=1), ultimo + pd.Timedelta(days=1))
        folds.append((inicio, fim))
    return folds


def corrigir_vies(g, janela=28, coluna="ons", gap=GAP):
    """`coluna` menos o seu erro médio recente na mesma hora, com erros conhecidos até T−gap.

    g: linhas de um só subsistema e peça, com colunas data, hora, `coluna` e real. O DESSEM tem viés de nível
    contra o balanço (no Sudeste, +1,1 GW na carga em 2026), e uma mesa corrigiria isso antes de qualquer ML.
    """
    saida = pd.Series(np.nan, index=g.index)
    for _, h in g.groupby("hora"):
        erro = (h[coluna] - h["real"]).set_axis(h["data"]).asfreq("D")
        vies = erro.shift(gap).rolling(janela, min_periods=7).mean().reindex(h["data"]).to_numpy()
        saida.loc[h.index] = h[coluna].to_numpy() - vies
    return saida


def corrigir_vies_semana(g, coluna="ons_ant", gap=GAP, semanas=4):
    """Como corrigir_vies, mas o viés é medido por hora E dia da semana (últimas `semanas` ocorrências conhecidas).

    Em D+2 a programação disponível é a de T−1: na segunda-feira, ela é a de domingo. O erro sistemático
    dessa troca de dia (domingo → segunda, sexta → sábado) só aparece separando por dia da semana.
    """
    saida = pd.Series(np.nan, index=g.index)
    dia_semana = g["data"].dt.day_of_week
    for _, h in g.groupby([g["hora"], dia_semana]):
        erro = (h[coluna] - h["real"]).set_axis(h["data"]).asfreq("7D")
        # Ocorrência anterior do mesmo dia da semana = 7 dias antes; só serve se 7 ≥ gap (sempre, até D+6).
        passos = int(np.ceil(gap / 7))
        vies = erro.shift(passos).rolling(semanas, min_periods=2).mean().reindex(h["data"]).to_numpy()
        saida.loc[h.index] = h[coluna].to_numpy() - vies
    return saida


def preparar_fonte(serie, previsoes, gap=GAP):
    """serie: gerada por hora. previsoes: índice horário, uma coluna por variável prevista. Devolve linhas data × hora.

    gap: dia mais recente com geração verificada (2 para D+1, 3 para D+2). r2 guarda o nome, mas usa o lag max(2, gap).
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
        # Razão limitada a 3: no amanhecer o nível é quase zero e a razão explode, dominando o GBM (que junta as horas).
        x = pd.DataFrame({"y": y, "nivel": nivel, "alvo": (y / nivel).where(valido).clip(upper=RAZAO_MAXIMA),
                          "r2": (y.shift(recente) / nivel).where(valido), "r7": (y.shift(max(7, gap)) / nivel).where(valido),
                          "tend": (y.shift(gap).rolling(7, min_periods=4).mean() / nivel).where(valido),
                          "persistencia": y.shift(recente), "media7": y.shift(gap).rolling(7, min_periods=4).mean()}, index=g.index)
        for coluna in colunas_prev:
            # Compara a previsão com previsões anteriores (já conhecidas) da mesma hora.
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
    """Treina até `inicio` e prevê [inicio, fim). Noites (nível ~0) ficam com previsão zero.

    operacional=True prevê dias cujo valor real ainda não existe (uso em produção, não em backtest).
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
    """ons: programação do próprio dia T (só existe na véspera de T).
    ons_ant: a programação mais recente que existe na hora da decisão, a de T−(horizonte−1). Em D+1 é a mesma."""
    serie = d[peca].rename("ons")
    # União dos índices: em D+2 a programação de T ainda não existe, mas a de T−1 (ons_ant) sim.
    ref = pd.concat([serie, serie.shift(freq=pd.Timedelta(days=horizonte - 1)).rename("ons_ant")], axis=1)
    ref = ref.rename_axis("instante").reset_index()
    return ref.assign(data=ref["instante"].dt.normalize(), hora=ref["instante"].dt.hour)[["data", "hora", "ons", "ons_ant"]]


def backtest_pecas(balanco, dessem, previsoes, temperatura, folds, log=print, horizonte=1, operacional=False):
    """Devolve uma tabela longa: data, hora, subsistema, peca (carga/eolica/solar), real e cada modelo.

    horizonte: 1 = D+1 (decisão na véspera), 2 = D+2... Os dados verificados vão até T−(horizonte+1), e
    `previsoes` e `temperatura` devem vir da rodada emitida horizonte+1 dias antes de cada hora.
    operacional: prevê também dias sem valor real (o balanço deve ter linhas vazias para esses dias).
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
        # Carga: mesma estrutura do modelo de D+1, agora com a carga do balanço como alvo.
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
        log(f"Peças {subsistema} ok")
    return pd.concat(saidas, ignore_index=True)
