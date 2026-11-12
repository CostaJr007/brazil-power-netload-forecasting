r"""Audit: how the operational forecast would have done over recent days, compared with what happened.

For each target day T and step (D+1, D+2), rebuilds the forecast as of 10 pm the night before the decision:
  - balance cut at D−1 and ONS schedule cut at D+1 (what existed that night);
  - archived weather forecast issued 48 h (D+1) or 72 h (D+2) before, as in training;
  - recipes frozen from the results JSON files, with no tuning on the audited week.
Caveat: "actual" is today's balance, already revised; the most recent day is still preliminary.

Output: docs/inventory/auditoria_previsoes.json, data/gold/auditoria_previsoes.parquet and a terminal summary.
Run: .\.venv\Scripts\python.exe scripts/auditar_previsoes.py [--inicio 2026-11-04 --fim 2026-11-10]
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire import DATA_DIR  # noqa: E402
from models.dados import carregar_balanco_horario, carregar_dessem, carregar_previsao_renovaveis, carregar_temperatura_prevista, conectar  # noqa: E402
from models.operacional import UM_DIA, carga_liquida, dias_completos, horizonte_efetivo, prever_dia  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def receitas():
    ler = lambda nome: json.loads((RAIZ / f"docs/inventory/{nome}").read_text(encoding="utf-8"))["escolhas"]  # noqa: E731
    return {1: ler("carga_liquida_results.json"), 2: ler("carga_liquida_dmais2_results.json")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inicio")
    parser.add_argument("--fim")
    parser.add_argument("--reusar", action="store_true", help="só refaz o resumo a partir de data/gold/auditoria_previsoes.parquet")
    args = parser.parse_args()
    con = conectar()
    balanco, dessem = carregar_balanco_horario(con), carregar_dessem(con)
    con.close()
    verificados_hoje = dias_completos(balanco, "carga")
    fim = pd.Timestamp(args.fim) if args.fim else max(verificados_hoje)
    inicio = pd.Timestamp(args.inicio) if args.inicio else fim - 6 * UM_DIA
    escolhas = receitas()
    if args.reusar:
        tabela = pd.read_parquet(DATA_DIR / "gold/auditoria_previsoes.parquet")
        inicio, fim = tabela["alvo"].min(), tabela["alvo"].max()
        return resumir(tabela, inicio, fim, escolhas)
    insumos = {dia: (carregar_previsao_renovaveis(dia), carregar_temperatura_prevista(dia)) for dia in (2, 3)}
    partes = []
    for alvo in pd.date_range(inicio, fim, freq="D"):
        for passo in (1, 2):
            decisao = alvo - passo * UM_DIA
            bal = balanco[balanco["instante"] < decisao]
            des = dessem[dessem["instante"] < decisao + 2 * UM_DIA]
            h = horizonte_efetivo(alvo, dias_completos(bal, "carga"), dias_completos(des, "demanda"))
            if h is None:
                print(f"{alvo.date()} D+{passo}: sem dados suficientes naquela noite")
                continue
            previsoes, temperatura = insumos[h + 1]
            pecas = prever_dia(alvo, h, bal, des, previsoes, temperatura, escolhas[h])
            partes.append(pecas.assign(decisao=decisao, alvo=alvo, passo=passo))
            print(f"{alvo.date()} D+{passo} ok (horizonte treinado D+{h})", flush=True)
    tabela = pd.concat(partes, ignore_index=True)
    # Real: balanço de hoje. ONS do próprio dia: DESSEM de T (só existia na véspera de T).
    real = balanco.assign(data=balanco["instante"].dt.normalize(), hora=balanco["instante"].dt.hour)
    real = real.melt(id_vars=["subsistema", "data", "hora"], value_vars=["carga", "eolica", "solar"], var_name="peca", value_name="real")
    tabela = tabela.drop(columns=["real"]).merge(real, on=["subsistema", "data", "hora", "peca"], how="left")
    tabela.to_parquet(DATA_DIR / "gold/auditoria_previsoes.parquet", index=False)
    return resumir(tabela, inicio, fim, escolhas)


def resumir(tabela, inicio, fim, escolhas):
    resultado ={"periodo": [str(inicio.date()), str(fim.date())], "receitas": {f"D+{k}": v for k, v in escolhas.items()}, "passos": {}}
    for passo, g in tabela.groupby("passo"):
        regua = "ons" if passo == 1 else "ons_ant_semana"
        colunas = list(dict.fromkeys(["previsto", "real", regua, "ons"]))
        liq = None
        for coluna in colunas:
            parte = carga_liquida(g, coluna)
            liq = parte if liq is None else liq.merge(parte, on=["subsistema", "data", "hora"], how="outer")
        liq = liq.dropna(subset=["previsto", "real"])
        sin = liq[liq["subsistema"] == "SIN"].copy()
        for c in ("previsto", regua):
            sin[f"erro_{c}"] = sin[c] - sin["real"]
        diario = []
        for data, d in sin.groupby("data"):
            pico_real = d.loc[d["real"].idxmax()]
            pico_prev = d.loc[d["previsto"].idxmax()]
            diario.append({"data": f"{data.date()} ({DIAS_SEMANA[data.day_of_week]})",
                           "real_medio_mw": round(d["real"].mean()), "previsto_medio_mw": round(d["previsto"].mean()),
                           "mae_modelo_mw": round(d["erro_previsto"].abs().mean()), f"mae_{regua}_mw": round(d[f"erro_{regua}"].abs().mean()),
                           "vies_modelo_mw": round(d["erro_previsto"].mean()),
                           "pico_real_mw": round(pico_real["real"]), "pico_previsto_mw": round(pico_prev["previsto"]),
                           "hora_pico_real": int(pico_real["hora"]), "hora_pico_prevista": int(pico_prev["hora"]),
                           "venceu_regua": bool(d["erro_previsto"].abs().mean() < d[f"erro_{regua}"].abs().mean())})
        por_peca = {}
        for (peca, sub), p in g.dropna(subset=["previsto", "real", regua]).groupby(["peca", "subsistema"]):
            por_peca.setdefault(peca, {})[sub] = {"mae_modelo": round(float((p["previsto"] - p["real"]).abs().mean())),
                                                  f"mae_{regua}": round(float((p[regua] - p["real"]).abs().mean())),
                                                  "vies_modelo": round(float((p["previsto"] - p["real"]).mean()))}
        mae_m, mae_r = sin["erro_previsto"].abs().mean(), sin[f"erro_{regua}"].abs().mean()
        resultado["passos"][f"D+{passo}"] = {
            "regua": regua, "horas_sin": int(len(sin)),
            "mae_sin_modelo_mw": round(float(mae_m)), f"mae_sin_{regua}_mw": round(float(mae_r)),
            "ganho_vs_regua_pct": round(100 * (1 - mae_m / mae_r), 1),
            "mape_sin_modelo_pct": round(float((sin["erro_previsto"].abs() / sin["real"].abs()).mean() * 100), 2),
            "dias_vencendo_a_regua": f"{sum(d['venceu_regua'] for d in diario)}/{len(diario)}",
            "acerto_hora_do_pico": f"{sum(abs(d['hora_pico_real'] - d['hora_pico_prevista']) <= 1 for d in diario)}/{len(diario)} (±1 h)",
            "diario": diario, "por_peca_subsistema": por_peca,
            "por_hora_mae_modelo": {int(h): round(float(v)) for h, v in sin.groupby("hora")["erro_previsto"].apply(lambda s: s.abs().mean()).items()},
        }
    destino = RAIZ / "docs/inventory/auditoria_previsoes.json"
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for passo, r in resultado["passos"].items():
        print(f"\n== {passo} (régua: {r['regua']}) | MAE SIN modelo {r['mae_sin_modelo_mw']} MW vs régua {r[f'mae_sin_{r['regua']}_mw']} MW "
              f"({r['ganho_vs_regua_pct']:+}%), MAPE {r['mape_sin_modelo_pct']}%, venceu {r['dias_vencendo_a_regua']} dias, pico {r['acerto_hora_do_pico']}")
        print(pd.DataFrame(r["diario"]).to_string(index=False))
    return 0 if np.isfinite(tabela["previsto"]).any() else 1


if __name__ == "__main__":
    raise SystemExit(main())
