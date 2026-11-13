"""Static HTML dashboard (single file, no server): docs/dashboard/index.html, opens in any browser.

Reads the same star-schema tables as Power BI (data/bi/*.parquet, from scripts/exportar_bi.py), pre-aggregates them
into small JSON blocks and embeds them in one HTML page with Plotly.js (CDN). Numbers therefore match the Power BI
report and the paper.

Design: consulting style with a purple/black palette (purple #A100FF = model, grey #66646E = benchmark, lilac band),
action titles that state the conclusion, one accent colour, small multiples instead of many coloured lines (validated
for colour-vision deficiency), source notes on every tab.

Run: .\\.venv\\Scripts\\python.exe scripts/gerar_dashboard_html.py   (after scripts/exportar_bi.py)
Open docs/dashboard/index.html in a browser; add #tab=scoreboard (forecast, scoreboard, drivers, audit, system).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire import DATA_DIR  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
BI = DATA_DIR / "bi"
SAIDA = RAIZ / "docs" / "dashboard" / "index.html"
SUBS = ["SIN", "SE", "S", "NE", "N"]
NOMES = {"SIN": "National grid", "SE": "Southeast/Center-West", "S": "South", "NE": "Northeast", "N": "North"}
PERIODOS = {"validation (2026)": "2026 · validation", "selection (2025)": "2025 · selection"}


def r(x, nd=0):
    """Round for JSON (NaN -> None)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x), nd) if nd else int(round(float(x)))


def lista(s, nd=0):
    return [r(v, nd) for v in s]


def ler(nome):
    return pd.read_parquet(BI / f"{nome}.parquet")


def placar(nl, dd):
    """KPIs and charts for every horizon × period × subsystem."""
    nl = nl.merge(dd[["date", "day_type"]], on="date", how="left")
    nl["em"] = (nl["forecast"] - nl["actual"]).abs()
    nl["eb"] = (nl["benchmark"] - nl["actual"]).abs()
    nl["bias"] = nl["forecast"] - nl["actual"]
    saida = {}
    for (hz, per, sub), g in nl.groupby(["horizon", "period", "subsystem"]):
        dia = g.groupby("date").agg(em=("em", "mean"), eb=("eb", "mean"))
        banda = g.dropna(subset=["band_low"])
        cobertura = ((banda["actual"] >= banda["band_low"]) & (banda["actual"] <= banda["band_high"])).mean() if len(banda) else np.nan
        mes = g.assign(m=g["date"].dt.strftime("%Y-%m")).groupby("m")[["em", "eb"]].mean()
        hora = g.groupby("hour")[["em", "eb"]].mean()
        tipo = g.groupby("day_type").agg(em=("em", "mean"), eb=("eb", "mean"), bias=("bias", "mean"), dias=("date", "nunique"))
        limpo = g[~g["telemetry_outage"]].groupby("date")["bias"].mean()
        mae_m, mae_b = g["em"].mean(), g["eb"].mean()
        saida[f"{hz}|{per}|{sub}"] = {
            "mae_m": r(mae_m), "mae_b": r(mae_b), "gain": r(100 * (1 - mae_m / mae_b), 1),
            "win": r(100 * (dia["em"] < dia["eb"]).mean()), "days": int(dia.shape[0]), "cov": r(100 * cobertura, 1),
            "month": {"x": list(mes.index), "m": lista(mes["em"]), "b": lista(mes["eb"])},
            "hour": {"m": lista(hora["em"]), "b": lista(hora["eb"])},
            "dtype": [{"t": t, "m": r(v["em"]), "b": r(v["eb"]), "bias": r(v["bias"]), "d": int(v["dias"])}
                      for t, v in tipo.reindex(["weekday", "weekend", "holiday"]).dropna().iterrows()],
            "bias": {"x": [d.strftime("%Y-%m-%d") for d in limpo.index], "y": lista(limpo)},
            "outages": int(g.loc[g["telemetry_outage"], "date"].nunique()),
        }
    return saida


def componentes(cp):
    cp = cp.assign(em=(cp["forecast"] - cp["actual"]).abs(), eb=(cp["benchmark"] - cp["actual"]).abs(), bias=cp["forecast"] - cp["actual"])
    saida = {}
    for (hz, per), g in cp.groupby(["horizon", "period"]):
        mat = g.groupby(["component", "subsystem"])[["em", "eb"]].mean()
        tot = g.groupby("component")[["em", "eb"]].mean()
        mes = g.assign(m=g["date"].dt.strftime("%Y-%m")).groupby(["component", "m"])["bias"].mean().unstack(0)
        saida[f"{hz}|{per}"] = {
            "matrix": {c: {s: {"m": r(mat.loc[(c, s), "em"]), "b": r(mat.loc[(c, s), "eb"]),
                               "gain": r(100 * (1 - mat.loc[(c, s), "em"] / mat.loc[(c, s), "eb"]), 1)}
                           for s in ["SE", "S", "NE", "N"] if (c, s) in mat.index} for c in ["load", "wind", "solar"]},
            "total": {c: {"m": r(tot.loc[c, "em"]), "b": r(tot.loc[c, "eb"])} for c in ["load", "wind", "solar"]},
            "gain_all": r(100 * (1 - g["em"].mean() / g["eb"].mean()), 1),
            "bias": {"x": list(mes.index), **{c: lista(mes[c]) for c in ["load", "wind", "solar"] if c in mes}},
        }
    return saida


def previsao(fc):
    if fc.empty:
        return {}
    ult = fc["decision_date"].max()
    f = fc[fc["decision_date"] == ult]
    saida = {"decision": ult.strftime("%Y-%m-%d"), "series": {}}
    for (alvo, passo, sub), g in f.groupby(["date", "step", "subsystem"]):
        g = g.sort_values("hour")
        saida["series"][f"{alvo:%Y-%m-%d}|{passo}|{sub}"] = {
            "f": lista(g["forecast"]), "b": lista(g["benchmark"]), "lo": lista(g["band_low"]), "hi": lista(g["band_high"]),
            "h": lista(g["hour"]), "horizon": str(g["horizon"].iloc[0])}
    return saida


def auditoria(au):
    saida = {}
    for (passo, sub), g in au.groupby(["step", "subsystem"]):
        g = g.sort_values("timestamp")
        em, eb = (g["forecast"] - g["actual"]).abs(), (g["benchmark"] - g["actual"]).abs()
        dia = g.assign(em=em, eb=eb).groupby("date").agg(em=("em", "mean"), eb=("eb", "mean"), a=("actual", "mean"), f=("forecast", "mean"))
        saida[f"{passo}|{sub}"] = {
            "x": [t.strftime("%Y-%m-%d %H:00") for t in g["timestamp"]], "f": lista(g["forecast"]), "a": lista(g["actual"]),
            "mae_m": r(em.mean()), "mae_b": r(eb.mean()), "gain": r(100 * (1 - em.mean() / eb.mean()), 1),
            "start": g["date"].min().strftime("%b %d"), "end": g["date"].max().strftime("%b %d"),
            "days": [{"d": d.strftime("%a %b %d"), "m": r(v["em"]), "b": r(v["eb"]), "win": bool(v["em"] < v["eb"])} for d, v in dia.iterrows()],
        }
    return saida


def sistema(sd, st, pr):
    saida = {}
    for ano in sorted(sd["date"].dt.year.unique()):
        if ano < 2021:
            continue
        s = sd[sd["date"].dt.year == ano]
        mix = s[["hydro_mw", "wind_mw", "solar_mw", "thermal_mw"]].mean()
        semana = s.set_index("date")["inflow_pct_ltm"].resample("W").mean()
        sto = st[st["date"].dt.year == ano].pivot_table(index="date", columns="subsystem", values="storage_pct").resample("W").mean()
        pri = pr[pr["date"].dt.year == ano].pivot_table(index="date", columns="subsystem", values="price_est").resample("W").mean()
        saida[str(int(ano))] = {
            "mix": {k.replace("_mw", ""): r(100 * v / mix.sum(), 1) for k, v in mix.items()},
            "mix_mw": {k.replace("_mw", ""): r(v) for k, v in mix.items()},
            "inflow": {"x": [d.strftime("%Y-%m-%d") for d in semana.index], "y": lista(semana)},
            "storage": {"x": [d.strftime("%Y-%m-%d") for d in sto.index], **{c: lista(sto[c], 1) for c in sto.columns}},
            "price": {"x": [d.strftime("%Y-%m-%d") for d in pri.index], **{c: lista(pri[c], 1) for c in pri.columns}},
            "price_mean": {c: r(pri[c].mean()) for c in pri.columns},
            "storage_last": {c: r(sto[c].dropna().iloc[-1], 1) if sto[c].notna().any() else None for c in sto.columns},
        }
    return saida


def main():
    dd = ler("dim_date")
    dados = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "names": NOMES, "periods": PERIODOS,
        "score": placar(ler("fact_net_load"), dd),
        "drivers": componentes(ler("fact_components")),
        "forecast": previsao(ler("fact_forecast")),
        "audit": auditoria(ler("fact_audit")),
        "system": sistema(ler("fact_system_daily"), ler("fact_storage_daily"), ler("fact_price_daily")),
    }
    modelo = (Path(__file__).resolve().parent / "dashboard_template.html").read_text(encoding="utf-8")
    html = modelo.replace("/*__DATA__*/null", json.dumps(dados, ensure_ascii=False, separators=(",", ":")))
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(html, encoding="utf-8", newline="\n")
    print(f"{SAIDA} ({SAIDA.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
