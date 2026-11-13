"""Backtest of the hourly D+1 load forecast; writes docs/inventory/carga_d1_results.json.

Run scripts/baixar_temperatura_prevista.py first. Reads Gold; no network.
Model choice uses 2023-2024; 2025-2026 is reserved to confirm the choice without selection bias.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.carga_d1 import backtest_d1  # noqa: E402
from models.dados import carregar_carga_horaria, carregar_temperatura_prevista, conectar  # noqa: E402
from models.validation import annual_folds, block_bootstrap_diff  # noqa: E402

MODELOS = ["ons", "ons_vies28", "ridge_ons_sem_temp", "ridge_ons", "gbm_ons", "combinado", "ridge_ons_limite", "ridge_sem_ons", "gbm_sem_ons"]
REALIZAVEIS = [m for m in MODELOS if m != "ridge_ons_limite"]
DESENVOLVIMENTO, CONFIRMACAO = (2023, 2024), (2025, 2026)


def metricas(frame, modelo):
    erro = frame[modelo] - frame["carga"]
    return {"mae": round(float(erro.abs().mean()), 1), "mape": round(float((erro.abs() / frame["carga"]).mean() * 100), 3),
            "vies_pct": round(float((erro / frame["carga"]).mean() * 100), 3)}


def diario(frame):
    """Daily mean and daily peak, only on days with all 24 hours."""
    colunas = ["carga"] + MODELOS
    grupos = frame.groupby(["subsistema", "data"])
    completos = grupos["hora"].transform("size") == 24
    medias = frame[completos].groupby(["subsistema", "data", "ano"])[colunas].mean().reset_index()
    picos = frame[completos].groupby(["subsistema", "data", "ano"])[colunas].max().reset_index()
    return medias, picos


def sin(frame):
    """Sum of the 4 subsystems each hour: the aggregate that matters most for the national price."""
    colunas = ["carga"] + MODELOS
    grupo = frame.groupby(["data", "hora", "ano"])
    completos = grupo["subsistema"].transform("size") == 4
    return frame[completos].groupby(["data", "hora", "ano"])[colunas].sum().reset_index()


def tabela(frame):
    return {m: metricas(frame, m) for m in MODELOS}


def intervalo(frame, a, b):
    media, baixo, alto = block_bootstrap_diff(frame["data"], (frame[a] - frame["carga"]).abs(), (frame[b] - frame["carga"]).abs())
    return {"comparacao": f"{a} - {b}", "dif_mae": round(media, 2), "ic95": [round(baixo, 2), round(alto, 2)]}


def main():
    con = conectar()
    carga = carregar_carga_horaria(con)
    con.close()
    temperatura = carregar_temperatura_prevista()
    ultimo = min(carga.dropna(subset=["carga"])["instante"].max(), temperatura.dropna(subset=["temp_prev_48h"])["instante"].max()).normalize() - pd.Timedelta(days=1)
    previsoes = backtest_d1(carga, temperatura, annual_folds(2023, ultimo))
    previsoes = previsoes.dropna(subset=MODELOS)
    desenvolvimento = previsoes[previsoes["ano"].isin(DESENVOLVIMENTO)]
    confirmacao = previsoes[previsoes["ano"].isin(CONFIRMACAO)]
    escolhido = min(REALIZAVEIS, key=lambda m: metricas(desenvolvimento, m)["mae"])
    medias, picos = diario(previsoes)
    agregado = sin(previsoes)
    resultado = {
        "escolhido_em_2023_2024": escolhido,
        "periodo": {"inicio": str(previsoes["data"].min().date()), "fim": str(previsoes["data"].max().date()),
                    "linhas": len(previsoes)},
        "horario": {"todos": tabela(previsoes), "desenvolvimento": tabela(desenvolvimento), "confirmacao": tabela(confirmacao)},
        "por_subsistema_confirmacao": {s: tabela(g) for s, g in confirmacao.groupby("subsistema")},
        "por_ano": {str(a): {m: metricas(g, m)["mape"] for m in MODELOS} for a, g in previsoes.groupby("ano")},
        "media_diaria": {"todos": tabela(medias), "confirmacao": tabela(medias[medias["ano"].isin(CONFIRMACAO)])},
        "pico_diario_confirmacao": tabela(picos[picos["ano"].isin(CONFIRMACAO)]),
        "sin_horario_confirmacao": tabela(agregado[agregado["ano"].isin(CONFIRMACAO)]),
        "por_hora_mape_confirmacao": {int(h): {m: metricas(g, m)["mape"] for m in ("ons", "ons_vies28", escolhido)} for h, g in confirmacao.groupby("hora")},
        "testes_confirmacao": [intervalo(confirmacao, a, b) for a, b in
                               [(escolhido, "ons"), (escolhido, "ons_vies28"), ("ridge_ons", "ridge_ons_sem_temp"),
                                ("ridge_ons_limite", "ridge_ons"), ("combinado", "ons_vies28"), ("ridge_sem_ons", "ons")]],
    }
    destino = Path(__file__).resolve().parents[1] / "docs/inventory/carga_d1_results.json"
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=1))
    return 0 if np.isfinite(previsoes["ons"]).all() else 1


if __name__ == "__main__":
    raise SystemExit(main())
