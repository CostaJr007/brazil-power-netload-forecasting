"""Is a new model worth it? Diagnosis of the 2026 residuals before any retraining.

Idea: if the error of the current recipe (already out of sample, from the walk-forward backtest) is unrelated
to any new variable, retraining with it will gain nothing. If it is related, the relationship shows how much
could be gained. Three tests:
  1. Correlation and band means: residual × candidate variables (accumulated heat, recent ONS bias...).
  2. Monthly walk-forward second stage in 2026: a GBM learns the residual from earlier months only and
     corrects the forecast. Variants: calendar only (control), + weather, + ONS bias regime.
  3. Prediction interval by resampling past residuals (empirical Monte Carlo): coverage in 2026.

Everything uses only what existed at 10 pm the day before (ONS bias known up to T−gap; archived forecast
temperature). Run: .\\.venv\\Scripts\\python.exe scripts/diagnostico/residuos_2026.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from models.carga import calendario  # noqa: E402
from models.dados import carregar_temperatura_prevista  # noqa: E402
from models.operacional import carga_liquida  # noqa: E402
from models.validation import block_bootstrap_diff  # noqa: E402

CONFIG = {1: ("previsoes_carga_liquida", "carga_liquida_results.json", 2, "ons"),
          2: ("previsoes_carga_liquida_dmais2", "carga_liquida_dmais2_results.json", 3, "ons_ant_semana")}
INICIO_TESTE = pd.Timestamp("2026-01-01")


def previsoes(horizonte):
    arquivo, receitas, _, regua = CONFIG[horizonte]
    p = pd.read_parquet(RAIZ / f"data/gold/{arquivo}.parquet")
    escolhas = json.loads((RAIZ / f"docs/inventory/{receitas}").read_text(encoding="utf-8"))["escolhas"]
    p["previsto"] = np.nan
    for peca, receita in escolhas.items():
        linhas = p["peca"] == peca
        p.loc[linhas, "previsto"] = p.loc[linhas, receita]
    liq = None
    for coluna in dict.fromkeys(["previsto", "real", regua, "ons"]):
        parte = carga_liquida(p, coluna)
        liq = parte if liq is None else liq.merge(parte, on=["subsistema", "data", "hora"], how="outer")
    return p, liq.dropna(subset=["previsto", "real"]), escolhas


def variaveis(p, horizonte):
    """Candidates per subsystem × day × hour, all known at decision time."""
    gap = CONFIG[horizonte][2]
    t = carregar_temperatura_prevista(horizonte + 1)
    col = "temp_prev_48h" if horizonte == 1 else "temp_prev"
    t = t.assign(subsistema=t["subsistema"].replace({"SECO": "SE"}), data=t["instante"].dt.normalize(), hora=t["instante"].dt.hour)
    t = t.groupby(["subsistema", "data", "hora"], as_index=False)[col].mean().rename(columns={col: "temp"})
    dia = t.groupby(["subsistema", "data"]).agg(tmed=("temp", "mean"), tmax=("temp", "max")).reset_index()
    saida = []
    for sub, g in dia.groupby("subsistema"):
        g = g.set_index("data").asfreq("D")
        normal = g["tmed"].shift(gap).rolling(30, min_periods=20).mean()   # recent climate the model already knows
        anom = g["tmed"] - normal
        g = g.assign(anom_dia=anom,
                     calor_3d=anom.rolling(3, min_periods=2).mean(),          # accumulated heat (forecast for the 3 days)
                     dias_quentes=(g["tmax"] >= 32).astype(int).groupby((g["tmax"] < 32).cumsum()).cumsum(),
                     subsistema=sub)
        saida.append(g.reset_index())
    dia = pd.concat(saida)
    # ONS load-bias regime: daily error (ONS − actual), known only up to T−gap.
    c = p[p["peca"] == "carga"].assign(erro=lambda f: f["ons"] - f["real"])
    vies = []
    for sub, g in c.groupby("subsistema"):
        e = g.groupby("data")["erro"].mean().asfreq("D").shift(gap)
        vies.append(pd.DataFrame({"subsistema": sub, "data": e.index, "vies_3d": e.rolling(3, min_periods=2).mean().values,
                                  "vies_28d": e.rolling(28, min_periods=20).mean().values}))
    vies = pd.concat(vies)
    vies["vies_div"] = vies["vies_3d"] - vies["vies_28d"]
    vies["vies_virou"] = (np.sign(vies["vies_3d"]) != np.sign(vies["vies_28d"])).astype(int)
    x = t.merge(dia, on=["subsistema", "data"], how="left").merge(vies, on=["subsistema", "data"], how="left")
    cal = calendario(pd.DatetimeIndex(x["data"].unique()))[["dia_semana", "feriado", "vespera", "pos_feriado", "ponte"]]
    return x.merge(cal, left_on="data", right_index=True, how="left")


GRUPOS = {"control (hour, weekday, holiday)": ["hora", "dia_semana", "feriado", "vespera", "pos_feriado", "ponte"]}
GRUPOS["+ tempo (calor, calor acumulado)"] = GRUPOS["control (hour, weekday, holiday)"] + ["temp", "tmax", "anom_dia", "calor_3d", "dias_quentes"]
GRUPOS["+ ONS bias regime"] = GRUPOS["+ tempo (calor, calor acumulado)"] + ["vies_3d", "vies_28d", "vies_div", "vies_virou"]


def segundo_estagio(base, colunas):
    """Monthly walk-forward: learns the residual from earlier months and corrects the next month."""
    corr = pd.Series(np.nan, index=base.index)
    for mes in pd.date_range(INICIO_TESTE, base["data"].max(), freq="MS"):
        treino = base[base["data"] < mes - pd.Timedelta(days=1)]
        teste = base[(base["data"] >= mes) & (base["data"] < mes + pd.offsets.MonthBegin(1))]
        if teste.empty:
            continue
        modelo = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=80,
                                               l2_regularization=1.0, random_state=0,
                                               categorical_features=[len(colunas)])
        modelo.fit(treino[colunas + ["sub_cod"]], treino["residuo"])
        corr.loc[teste.index] = modelo.predict(teste[colunas + ["sub_cod"]])
    return base["previsto"] - corr


def sin(frame, coluna):
    return frame.groupby(["data", "hora"])[[coluna, "real"]].sum(min_count=1)


def analisar(horizonte):
    regua = CONFIG[horizonte][3]
    p, liq, escolhas = previsoes(horizonte)
    subs = liq[liq["subsistema"] != "SIN"].copy()
    subs["residuo"] = subs["previsto"] - subs["real"]
    base = subs.merge(variaveis(p, horizonte), on=["subsistema", "data", "hora"], how="left")
    base["sub_cod"] = base["subsistema"].astype("category").cat.codes
    base = base.sort_values(["data", "subsistema", "hora"], ignore_index=True)
    teste = base[base["data"] >= INICIO_TESTE]
    print(f"\n================ D+{horizonte}  (receitas {escolhas}) ================")
    print(f"2026: {teste['data'].min().date()} to {teste['data'].max().date()}, {teste['data'].nunique()} days")

    # 1. Relationship between residual and candidates (2026, net load per subsystem)
    print("\n1) Correlation of the residual (forecast − actual) with each variable, 2026:")
    cand = ["temp", "anom_dia", "calor_3d", "dias_quentes", "vies_3d", "vies_div", "vies_virou", "feriado"]
    tab = teste.groupby("subsistema").apply(lambda g: g[cand].corrwith(g["residuo"]), include_groups=False).round(2)
    print(tab.to_string())
    se = teste[teste["subsistema"] == "SE"].copy()
    se["faixa_calor"] = pd.qcut(se["calor_3d"], 5, labels=["muito frio", "frio", "normal", "quente", "muito quente"])
    print("\n   SE, mean residual by accumulated-heat band (MW; negative = under-forecast):")
    print(se.groupby("faixa_calor", observed=True)["residuo"].agg(["mean", "count"]).round(0).to_string())
    se["vies_regime"] = np.where(se["vies_virou"] == 1, "bias flipped", "bias stable")
    print("\n   SE, mean |error| by ONS bias regime:")
    print(se.groupby("vies_regime")["residuo"].agg(mae=lambda s: s.abs().mean(), vies="mean", n="count").round(0).to_string())

    # 2. Second stage: can these variables correct the residual?
    print("\n2) Monthly walk-forward second stage in 2026 (national, hourly net load):")
    s0 = sin(teste.assign(x=teste["previsto"]), "x")
    mae0 = (s0["x"] - s0["real"]).abs().mean()
    r = sin(liq[(liq["subsistema"] != "SIN") & (liq["data"] >= INICIO_TESTE)], regua)
    print(f"   current recipe: MAE {mae0:,.0f} MW | benchmark {regua}: {(r[regua] - r['real']).abs().mean():,.0f} MW")
    resultados = {}
    for nome, colunas in GRUPOS.items():
        corrigido = segundo_estagio(base, colunas)
        t2 = base.assign(x=corrigido)[base["data"] >= INICIO_TESTE]
        s = sin(t2, "x").join(s0["x"].rename("x0"))
        ok = s["x"].notna()
        s = s[ok]
        mae = (s["x"] - s["real"]).abs().mean()
        datas = s.index.get_level_values("data")
        d, lo, hi = block_bootstrap_diff(datas, (s["x"] - s["real"]).abs(), (s["x0"] - s["real"]).abs())
        resultados[nome] = {"mae": round(mae), "dif": round(d), "ic": [round(lo), round(hi)]}
        print(f"   {nome:42s} MAE {mae:,.0f} MW  ({100 * (mae / mae0 - 1):+.1f}%)  dif {d:+.0f} MW, IC95 [{lo:+.0f}, {hi:+.0f}]")

    # 3. Empirical Monte Carlo: 80% interval resampling past residuals of the same hour
    print("\n3) 80% prediction interval by resampling residuals (national), coverage in 2026:")
    sin_all = sin(base.assign(x=base["previsto"]), "x").reset_index()
    sin_all["res"] = sin_all["x"] - sin_all["real"]
    cobre, larg = [], []
    rng = np.random.default_rng(0)
    for mes in pd.date_range(INICIO_TESTE, sin_all["data"].max(), freq="MS"):
        hist = sin_all[(sin_all["data"] < mes - pd.Timedelta(days=1)) & (sin_all["data"] >= mes - pd.Timedelta(days=120))]
        alvo = sin_all[(sin_all["data"] >= mes) & (sin_all["data"] < mes + pd.offsets.MonthBegin(1))]
        for hora, a in alvo.groupby("hora"):
            amostra = rng.choice(hist.loc[hist["hora"] == hora, "res"].dropna().to_numpy(), 5000)
            lo, hi = np.quantile(amostra, [0.1, 0.9])
            # real dentro de [prev − hi, prev − lo]
            cobre += list((a["real"] >= a["x"] - hi) & (a["real"] <= a["x"] - lo))
            larg.append(hi - lo)
    print(f"   coverage {100 * np.mean(cobre):.1f}% (target 80%), mean width {np.mean(larg):,.0f} MW")
    return resultados


if __name__ == "__main__":
    for h in (1, 2):
        analisar(h)
