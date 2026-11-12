"""Lógica fuzzy agrega valor? Dois usos testados com escolha em 2025 e confirmação em 2026.

Risco fuzzy por subsistema e dia (graus de pertinência de 0 a 1, combinados por OU = máximo):
  - "calor acumulado alto": rampa da anomalia de 3 dias da temperatura prevista;
  - "viés do ONS mudou":    rampa de |viés 3 dias − viés 28 dias| em desvios-padrão (conhecido até T−gap);
  - "dia especial":         feriado, véspera, dia seguinte ou ponte.

A) Banda de 80%: a largura cresce com o risco. Reamostra-se o resíduo padronizado r / (1 + k·risco),
   o que mantém a calibração. Métrica: Winkler (largura + penalidade de 10× o quanto o real sai da banda).
B) Previsão pontual (D+1, carga): quanto maior o risco do viés, menos se confia na correção de 28 dias:
   ons_fuzzy = μ·ons + (1 − μ)·ons_corrigido.

Executar: .\\.venv\\Scripts\\python.exe scripts/diagnostico/fuzzy_banda.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from residuos_2026 import previsoes, variaveis  # noqa: E402

from models.operacional import carga_liquida  # noqa: E402
from models.validation import block_bootstrap_diff  # noqa: E402

SELECAO = (pd.Timestamp("2025-08-01"), pd.Timestamp("2026-01-01"))
CONFIRMACAO = pd.Timestamp("2026-01-01")
ALFA = 0.2


def rampa(x, a, b):
    """Pertinência: 0 abaixo de a, 1 acima de b, linear entre os dois."""
    return ((x - a) / (b - a)).clip(0, 1)


def pertinencias(x, calor=(0.5, 3.0), vies=(0.5, 2.0)):
    x = x.copy()
    # Escala do viés: desvio-padrão só do período de seleção (nada de 2026 entra na régua).
    escala = x["subsistema"].map(x[x["data"] < SELECAO[1]].groupby("subsistema")["vies_div"].std())
    x["mu_calor"] = rampa(x["calor_3d"], *calor).fillna(0)
    x["mu_vies"] = rampa(x["vies_div"].abs() / escala, *vies).fillna(0)
    x["mu_dia"] = x[["feriado", "vespera", "pos_feriado", "ponte"]].max(axis=1).fillna(0)
    x["risco"] = x[["mu_calor", "mu_vies", "mu_dia"]].max(axis=1)
    return x


def winkler(real, lo, hi):
    return (hi - lo) + (2 / ALFA) * ((lo - real).clip(lower=0) + (real - hi).clip(lower=0))


def banda(sin, k, inicio, fim):
    """Intervalo de 80% por reamostragem dos resíduos padronizados dos 120 dias anteriores (mesma hora)."""
    linhas = []
    for mes in pd.date_range(inicio, fim, freq="MS", inclusive="left"):
        hist = sin[(sin["data"] < mes - pd.Timedelta(days=1)) & (sin["data"] >= mes - pd.Timedelta(days=120))]
        alvo = sin[(sin["data"] >= mes) & (sin["data"] < mes + pd.offsets.MonthBegin(1))]
        for hora, a in alvo.groupby("hora"):
            h = hist[hist["hora"] == hora]
            z = (h["res"] / (1 + k * h["risco"])).dropna()
            qlo, qhi = np.quantile(z, [ALFA / 2, 1 - ALFA / 2])
            fator = 1 + k * a["risco"]
            linhas.append(a.assign(lo=a["previsto"] - qhi * fator, hi=a["previsto"] - qlo * fator))
    b = pd.concat(linhas)
    return b.assign(dentro=(b["real"] >= b["lo"]) & (b["real"] <= b["hi"]), largura=b["hi"] - b["lo"],
                    winkler=winkler(b["real"], b["lo"], b["hi"]))


def testar_banda(horizonte):
    p, liq, _ = previsoes(horizonte)
    x = pertinencias(variaveis(p, horizonte))
    subs = liq[liq["subsistema"] != "SIN"].merge(x[["subsistema", "data", "hora", "risco"]], on=["subsistema", "data", "hora"], how="left")
    subs["peso"] = (subs["previsto"] - subs["real"]).abs()
    # Risco do SIN: média dos subsistemas ponderada pelo erro típico de cada um (SE pesa mais).
    pesos = subs[subs["data"] < SELECAO[1]].groupby("subsistema")["peso"].mean()
    subs["w"] = subs["subsistema"].map(pesos)
    sin = subs.groupby(["data", "hora"]).apply(lambda g: pd.Series({
        "previsto": g["previsto"].sum(), "real": g["real"].sum(),
        "risco": np.average(g["risco"].fillna(0), weights=g["w"])}), include_groups=False).reset_index()
    sin["res"] = sin["previsto"] - sin["real"]
    print(f"\n===== D+{horizonte}: banda de 80% =====")
    t = sin[sin["data"] >= CONFIRMACAO]
    t = t.assign(faixa=pd.cut(t["risco"], [-0.01, 0.2, 0.6, 1.0], labels=["baixo", "médio", "alto"]))
    print("O risco fuzzy separa os erros? |erro| médio do SIN em 2026 por faixa de risco:")
    print(t.groupby("faixa", observed=True)["res"].agg(mae=lambda s: s.abs().mean(), horas="count").round(0).to_string())
    grade = [0.0, 0.5, 1.0, 2.0, 3.0]
    sel = {k: banda(sin, k, *SELECAO)["winkler"].mean() for k in grade}
    k = min(sel, key=sel.get)
    print("Seleção (ago–dez/2025), Winkler médio por k:", {kk: round(v) for kk, v in sel.items()}, f"-> k = {k}")
    fim = sin["data"].max() + pd.Timedelta(days=1)
    for nome, kk in (("banda fixa por hora (k = 0)", 0.0), (f"banda fuzzy (k = {k})", k)):
        b = banda(sin, kk, CONFIRMACAO, fim)
        b = b.assign(faixa=pd.cut(b["risco"], [-0.01, 0.2, 0.6, 1.0], labels=["baixo", "médio", "alto"]))
        por = b.groupby("faixa", observed=True)["dentro"].mean().mul(100).round(0).to_dict()
        print(f"  2026 {nome:28s} cobertura {100 * b['dentro'].mean():.1f}% | largura {b['largura'].mean():,.0f} MW | "
              f"Winkler {b['winkler'].mean():,.0f} | cobertura por risco {por}")
        if kk == 0:
            base = b
    d, lo, hi = block_bootstrap_diff(b["data"], b["winkler"], base["winkler"])
    print(f"  Winkler fuzzy − fixa: {d:+.0f} MW, IC95 [{lo:+.0f}, {hi:+.0f}]")


def testar_pontual():
    p, liq, escolhas = previsoes(1)
    x = variaveis(p, 1)
    print("\n===== D+1: peso fuzzy da correção do viés do ONS na carga =====")
    resultados = {}
    for vies in [(0.5, 2.0), (1.0, 3.0), (2.0, 4.0)]:
        mu = pertinencias(x, vies=vies)[["subsistema", "data", "hora", "mu_vies"]]
        q = p.merge(mu, on=["subsistema", "data", "hora"], how="left")
        carga = q["peca"] == "carga"
        ml = q[["ridge", "gbm"]].mean(axis=1)
        ons_fz = q["mu_vies"].fillna(0) * q["ons"] + (1 - q["mu_vies"].fillna(0)) * q["ons_corrigido"]
        q.loc[carga, "previsto"] = 0.5 * ml[carga] + 0.5 * ons_fz[carga]
        liq_f = carga_liquida(q, "previsto").merge(liq[["subsistema", "data", "hora", "real", "previsto"]],
                                                   on=["subsistema", "data", "hora"], suffixes=("_fz", ""))
        s = liq_f[liq_f["subsistema"] == "SIN"].dropna()
        for periodo, f in (("2025", s[(s["data"] >= SELECAO[0]) & (s["data"] < SELECAO[1])]), ("2026", s[s["data"] >= CONFIRMACAO])):
            resultados.setdefault(vies, {})[periodo] = ((f["previsto_fz"] - f["real"]).abs().mean(), (f["previsto"] - f["real"]).abs().mean(), f)
        m25, b25, _ = resultados[vies]["2025"]
        print(f"  rampa {vies}: seleção 2025 MAE {m25:,.0f} vs receita {b25:,.0f} MW")
    melhor = min(resultados, key=lambda v: resultados[v]["2025"][0])
    m, b, f = resultados[melhor]["2026"]
    d, lo, hi = block_bootstrap_diff(f["data"], (f["previsto_fz"] - f["real"]).abs(), (f["previsto"] - f["real"]).abs())
    print(f"  escolhida {melhor} -> 2026 MAE {m:,.0f} vs receita {b:,.0f} MW ({100 * (m / b - 1):+.1f}%), dif {d:+.0f}, IC95 [{lo:+.0f}, {hi:+.0f}]")
    s = f[(f["data"] >= "2026-11-04") & (f["data"] <= "2026-11-07")]
    print(f"  semana auditada (04–07/11): MAE {(s['previsto_fz'] - s['real']).abs().mean():,.0f} vs receita {(s['previsto'] - s['real']).abs().mean():,.0f} MW")


if __name__ == "__main__":
    testar_banda(1)
    testar_banda(2)
    testar_pontual()
