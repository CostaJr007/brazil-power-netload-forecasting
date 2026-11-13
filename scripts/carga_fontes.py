"""Data-source ablation for D+1 load; writes docs/inventory/carga_fontes_results.json.

Run baixar_temperatura_prevista.py and baixar_vento_sol_previstos.py first. Reads Gold; no network.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire import DATA_DIR  # noqa: E402
from models.carga_fontes import GRUPOS, GRUPOS_PREVISAO, backtest_fontes  # noqa: E402
from models.dados import carregar_carga_horaria, carregar_extras, carregar_previstas_extras, carregar_temperatura_prevista, conectar  # noqa: E402
from models.validation import annual_folds, block_bootstrap_diff  # noqa: E402

RIDGES = ["ridge_" + g for g in GRUPOS]
GBMS = ["gbm_historico", "gbm_tudo"]
RECENTES = ["recente_" + g for g in GRUPOS_PREVISAO]


def mape(frame, modelo):
    return round(float(((frame[modelo] - frame["real"]).abs() / frame["real"]).mean() * 100), 3)


def intervalo(frame, a, b):
    media, baixo, alto = block_bootstrap_diff(frame["data"], (frame[a] - frame["real"]).abs(), (frame[b] - frame["real"]).abs())
    return {"comparacao": f"{a} - {b}", "dif_mae": round(media, 2), "ic95": [round(baixo, 2), round(alto, 2)]}


def resumir(frame, modelos, base):
    validos = frame.dropna(subset=modelos)
    return {"n": len(validos), "mape": {m: mape(validos, m) for m in modelos},
            "por_subsistema": {s: {m: mape(g, m) for m in modelos} for s, g in validos.groupby("subsistema")},
            "testes": [intervalo(validos, m, base) for m in modelos if m != base]}


def main():
    con = conectar()
    carga = carregar_carga_horaria(con)
    extras = carregar_extras(con)
    con.close()
    temperatura = carregar_temperatura_prevista()
    ultimo = carga.dropna(subset=["carga"])["instante"].max().normalize() - pd.Timedelta(days=1)
    # The wind and sun forecast is optional: without the file, the rest of the ablation runs.
    previstas = carregar_previstas_extras() if (DATA_DIR / "gold/previsao_vento_sol.parquet").exists() else None
    previsoes = backtest_fontes(carga, temperatura, extras, previstas, annual_folds(2023, ultimo))
    resultado = {}
    for alvo, g in previsoes.groupby("alvo"):
        resultado[alvo] = {"2023_2026": resumir(g, RIDGES + GBMS, "ridge_historico")}
        if previstas is not None:
            resultado[alvo]["previsao_real_2025_2026"] = resumir(g[g["ano"] >= 2025], RECENTES, "recente_historico")
    destino = Path(__file__).resolve().parents[1] / "docs/inventory/carga_fontes_results.json"
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
