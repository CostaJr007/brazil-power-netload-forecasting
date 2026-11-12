"""Backtest fatiado da carga de D+1; grava docs/inventory/sazonalidade_carga.json.

Escolhe entre modelo global, por estação e por janela de meses usando 2023-2024 e confirma em 2025-2026.
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.dados import carregar_carga_horaria, carregar_temperatura_prevista, conectar  # noqa: E402
from models.sazonalidade import backtest_sazonal  # noqa: E402
from models.validation import annual_folds, block_bootstrap_diff  # noqa: E402

MODELOS = ["ons", "ons_vies28", "global", "por_estacao", "por_mes_janela"]
CANDIDATOS = ["global", "por_estacao", "por_mes_janela"]


def mape(frame, modelo):
    return round(float(((frame[modelo] - frame["carga"]).abs() / frame["carga"]).mean() * 100), 3)


def tabela(frame, coluna):
    return {str(k): {m: mape(g, m) for m in MODELOS} for k, g in frame.groupby(coluna)}


def indice_sazonal(carga):
    """Carga de cada mês em relação à média do próprio ano; separa sazonalidade de crescimento."""
    d = carga.dropna(subset=["carga"]).copy()
    d["ano"], d["mes"] = d["instante"].dt.year, d["instante"].dt.month
    d = d[(d["ano"] >= 2022) & (d["ano"] <= 2025)]
    mensal = d.groupby(["subsistema", "ano", "mes"])["carga"].mean().reset_index()
    mensal["indice"] = mensal["carga"] / mensal.groupby(["subsistema", "ano"])["carga"].transform("mean")
    return mensal.groupby(["subsistema", "mes"])["indice"].mean().unstack("subsistema").round(3)


def main():
    con = conectar()
    carga = carregar_carga_horaria(con)
    con.close()
    temperatura = carregar_temperatura_prevista()
    ultimo = min(carga.dropna(subset=["carga"])["instante"].max(), temperatura.dropna(subset=["temp_prev_48h"])["instante"].max()).normalize() - pd.Timedelta(days=1)
    p = backtest_sazonal(carga, temperatura, annual_folds(2023, ultimo)).dropna(subset=MODELOS)
    desenvolvimento, confirmacao = p[p["ano"] <= 2024], p[p["ano"] >= 2025]
    escolhido = min(CANDIDATOS, key=lambda m: mape(desenvolvimento, m))
    def ic(a, b):
        return dict(zip(("dif_mae", "ic95_baixo", "ic95_alto"),
                        (round(v, 2) for v in block_bootstrap_diff(confirmacao["data"], (confirmacao[a] - confirmacao["carga"]).abs(), (confirmacao[b] - confirmacao["carga"]).abs()))))
    resultado = {"escolhido_em_2023_2024": escolhido, "linhas": len(p),
                 "mape_desenvolvimento": {m: mape(desenvolvimento, m) for m in MODELOS},
                 "mape_confirmacao": {m: mape(confirmacao, m) for m in MODELOS},
                 "testes_confirmacao": {"por_estacao - global": ic("por_estacao", "global"), "por_mes_janela - global": ic("por_mes_janela", "global")},
                 "por_estacao": tabela(confirmacao, "estacao"), "por_mes": tabela(confirmacao, "mes"), "por_faixa": tabela(confirmacao, "faixa"),
                 "por_tipo_dia": tabela(confirmacao, "tipo_dia"),
                 "subsistema_estacao": {f"{s}|{e}": {m: mape(g, m) for m in MODELOS} for (s, e), g in confirmacao.groupby(["subsistema", "estacao"])},
                 "indice_sazonal_mensal": indice_sazonal(carga).to_dict()}
    destino = Path(__file__).resolve().parents[1] / "docs/inventory/sazonalidade_carga.json"
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
