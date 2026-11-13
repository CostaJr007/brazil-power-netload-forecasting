"""Run the inflow and load model backtests and write docs/inventory/model_results.json.

Run: .\\.venv\\Scripts\\python.exe scripts/modelagem.py
Reads data/gold/energia.duckdb; no network and no changes to Gold.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.carga import backtest_carga  # noqa: E402
from models.dados import carregar_bacias, carregar_carga, carregar_temperatura, conectar  # noqa: E402
from models.ena import backtest_ena  # noqa: E402
from models.validation import annual_folds, block_bootstrap_diff, mae, skill  # noqa: E402

MODELOS_ENA = ["persistencia", "climatologia", "ou", "ridge_memoria", "ridge_arx", "ridge_chuva_placebo", "ridge_cenario",
               "ridge_cenario_placebo", "kalman_arx", "gbm_memoria", "gbm_chuva",
               "gbm_chuva_placebo", "gbm_cenario", "gbm_cenario_placebo"]
MODELOS_CARGA = ["naive", "ons", "ons_vies28", "gbm_calendario", "gbm_temp", "gbm_cenario", "gbm_cenario_placebo",
                 "ons_corrigido", "ons_corrigido_cenario"]


def erro_abs(frame, coluna, alvo):
    return (frame[coluna] - frame[alvo]).abs()


def intervalo(frame, a, b, alvo, data):
    """95% CI of the MAE difference between two models, with 14-day blocks."""
    v = frame.dropna(subset=[a, b])
    media, baixo, alto = block_bootstrap_diff(v[data], erro_abs(v, a, alvo), erro_abs(v, b, alvo))
    return {"comparacao": f"{a} - {b}", "dif_mae": round(media, 2), "ic95": [round(baixo, 2), round(alto, 2)]}


def resumo_ena(previsoes):
    saida = {}
    for h, grupo in previsoes.groupby("h"):
        validos = grupo.dropna(subset=MODELOS_ENA)
        base = mae(validos["y_alvo"], validos["persistencia"])
        clima = mae(validos["y_alvo"], validos["climatologia"])
        por_modelo = {m: {"mae_mwmed": round(mae(validos["y_alvo"], validos[m]), 1),
                          "skill_persistencia": round(skill(mae(validos["y_alvo"], validos[m]), base), 3),
                          "skill_climatologia": round(skill(mae(validos["y_alvo"], validos[m]), clima), 3)} for m in MODELOS_ENA}
        por_ano = {str(a): {m: round(skill(mae(g["y_alvo"], g[m]), mae(g["y_alvo"], g["persistencia"])), 3)
                            for m in ("ou", "ridge_arx", "ridge_cenario", "kalman_arx", "gbm_chuva", "gbm_cenario")} for a, g in validos.groupby("ano")}
        saida[f"h{h}"] = {"n": len(validos), "modelos": por_modelo, "skill_por_ano": por_ano,
                          "testes": [intervalo(validos, "ridge_arx", "ridge_memoria", "y_alvo", "data_alvo"),
                                     intervalo(validos, "ridge_arx", "ridge_chuva_placebo", "y_alvo", "data_alvo"),
                                     intervalo(validos, "ridge_cenario", "ridge_arx", "y_alvo", "data_alvo"),
                                     intervalo(validos, "ridge_cenario", "ridge_cenario_placebo", "y_alvo", "data_alvo"),
                                     intervalo(validos, "gbm_chuva", "gbm_memoria", "y_alvo", "data_alvo"),
                                     intervalo(validos, "gbm_chuva", "gbm_chuva_placebo", "y_alvo", "data_alvo"),
                                     intervalo(validos, "gbm_cenario", "gbm_chuva", "y_alvo", "data_alvo"),
                                     intervalo(validos, "gbm_cenario", "gbm_cenario_placebo", "y_alvo", "data_alvo")]}
    return saida


def resumo_bacias(previsoes, h):
    grupo = previsoes[previsoes["h"] == h].dropna(subset=MODELOS_ENA)
    linhas = []
    for bacia, g in grupo.groupby("bacia"):
        base = mae(g["y_alvo"], g["persistencia"])
        linhas.append({"bacia": bacia, "ena_media": round(float(g["y_alvo"].mean())), "mae_persistencia": round(base),
                       **{m: round(skill(mae(g["y_alvo"], g[m]), base), 3) for m in ("ou", "ridge_arx", "ridge_cenario", "gbm_chuva", "gbm_cenario")}})
    return sorted(linhas, key=lambda r: -r["ena_media"])


def resumo_carga(previsoes):
    saida = {}
    for subsistema, grupo in list(previsoes.groupby("subsistema")) + [("TODOS", previsoes)]:
        validos = grupo.dropna(subset=MODELOS_CARGA)
        base = mae(validos["carga"], validos["ons"])
        por_modelo = {m: {"mae_mwmed": round(mae(validos["carga"], validos[m]), 1),
                          "mape_pct": round(100 * float(np.mean(np.abs(validos[m] / validos["carga"] - 1))), 2),
                          "skill_ons": round(skill(mae(validos["carga"], validos[m]), base), 3)} for m in MODELOS_CARGA}
        feriados = validos[validos["feriado"] == 1]
        saida[subsistema] = {"n": len(validos), "modelos": por_modelo,
                             "mae_feriados": {m: round(mae(feriados["carga"], feriados[m]), 1) for m in ("naive", "ons", "gbm_calendario", "ons_corrigido")},
                             "skill_ons_por_ano": {str(a): {m: round(skill(mae(g["carga"], g[m]), mae(g["carga"], g["ons"])), 3)
                                                            for m in ("ons_vies28", "gbm_temp", "ons_corrigido", "ons_corrigido_cenario")}
                                                   for a, g in validos.groupby("ano")},
                             "testes": [intervalo(validos, "ons_corrigido", "ons", "carga", "data"),
                                        intervalo(validos, "ons_vies28", "ons", "carga", "data"),
                                        intervalo(validos, "ons_corrigido", "ons_vies28", "carga", "data"),
                                        intervalo(validos, "gbm_cenario", "gbm_cenario_placebo", "carga", "data"),
                                        intervalo(validos, "gbm_temp", "gbm_calendario", "carga", "data")]}
    return saida


def main():
    con = conectar()
    bacias = carregar_bacias(con)
    carga = carregar_carga(con)
    temperatura = carregar_temperatura(con)
    con.close()
    fim_temperatura = temperatura["data"].max()
    previsoes_ena, meias_vidas = backtest_ena(bacias, annual_folds(2021, bacias["data"].max()))
    previsoes_carga = backtest_carga(carga, temperatura, annual_folds(2022, min(fim_temperatura, carga["data"].max())))
    meia_vida = meias_vidas[meias_vidas["h"] == 1].groupby("bacia")["meia_vida"].median().round(1).sort_values(ascending=False)
    resultado = {"ena": resumo_ena(previsoes_ena), "ena_por_bacia_h7": resumo_bacias(previsoes_ena, 7),
                 "ou_meia_vida_dias": meia_vida.dropna().to_dict(),
                 "carga": resumo_carga(previsoes_carga),
                 "cobertura": {"ena_ate": str(bacias["data"].max().date()), "temperatura_ate": str(fim_temperatura.date()),
                               "bacias_avaliadas": int(previsoes_ena["bacia"].nunique())}}
    destino = Path(__file__).resolve().parents[1] / "docs/inventory/model_results.json"
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
