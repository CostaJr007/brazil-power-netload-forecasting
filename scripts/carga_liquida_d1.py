"""Backtest of net load (load − wind − solar) by summing components, against the ONS schedule.

--horizonte 1 (default): D+1, decided the day before; the benchmark is the same-day DESSEM schedule.
--horizonte 2: D+2, decided two days before; the same-day DESSEM does not exist yet. The benchmark is the latest
schedule (T−1) corrected by the bias of the same hour and weekday, which is what a desk would use. The same-day DESSEM
is kept only as a "D+1 world" reference, to measure the cost of deciding a day earlier.

Each component's model is chosen on the development period (2025) and confirmed on 2026, without selection bias.
Writes docs/inventory/carga_liquida_results.json (D+1) or carga_liquida_dmaisN_results.json, and forecasts to data/gold.
Run first: scripts/baixar_previsao_renovaveis.py, scripts/baixar_temperatura_prevista.py (with --dias N+1 for horizon
N > 1) and the balanco_dessem_detalhe backfill.
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
from models.renovaveis import backtest_pecas, corrigir_vies, corrigir_vies_semana, folds_trimestrais  # noqa: E402
from models.sazonalidade import faixa_horaria  # noqa: E402
from models.validation import block_bootstrap_diff  # noqa: E402

INICIO_CONFIRMACAO = pd.Timestamp("2026-01-01")
SINAIS = (("carga", 1), ("eolica", -1), ("solar", -1))


def mae(frame, coluna, alvo="real"):
    return float((frame[coluna] - frame[alvo]).abs().mean())


def resumo(frame, colunas, alvo="real", base="ons"):
    referencia = mae(frame, base, alvo)
    return {c: {"mae": round(mae(frame, c, alvo), 1), f"ganho_vs_{base}_pct": round(100 * (1 - mae(frame, c, alvo) / referencia), 1)} for c in colunas}


def intervalo(frame, a, b, alvo="real"):
    m, lo, hi = block_bootstrap_diff(frame["data"], (frame[a] - frame[alvo]).abs(), (frame[b] - frame[alvo]).abs())
    return {"comparacao": f"{a} - {b}", "dif_mae": round(m, 1), "ic95": [round(lo, 1), round(hi, 1)]}


def configuracao(horizonte):
    """Candidates per component, benchmark (base) and net-load models for each horizon."""
    if horizonte == 1:
        return {"base": "ons", "candidatos": ["ridge", "gbm", "media_ridge_gbm", "ridge_sem_previsao", "media_com_ons", "ons_corrigido", "media_com_ons_corrigido"],
                "referencias": ["ons", "persistencia", "media7"],
                "somas": ["real", "ons", "persistencia", "ons_corrigido", "ridge", "media_com_ons", "media_com_ons_corrigido"],
                "renomear": {"ridge": "pecas_ridge", "media_com_ons": "pecas_ml_com_ons", "media_com_ons_corrigido": "pecas_ml_com_ons_corrigido"},
                "modelos": ["ons", "ons_corrigido", "persistencia", "pecas_ridge", "pecas_escolhidas", "pecas_ml_com_ons", "pecas_ml_com_ons_corrigido"],
                "testes": [("ons_corrigido", "ons"), ("pecas_escolhidas", "ons"), ("pecas_escolhidas", "ons_corrigido"),
                           ("pecas_ml_com_ons_corrigido", "ons"), ("pecas_ml_com_ons_corrigido", "ons_corrigido")],
                "regua": "ons_corrigido"}
    return {"base": "ons_ant_semana",
            "candidatos": ["ridge", "gbm", "media_ridge_gbm", "ridge_sem_previsao", "ons_ant", "ons_ant_corrigido", "ons_ant_semana", "media_com_ons_ant_corrigido", "media_com_ons_ant_semana"],
            "referencias": ["persistencia", "media7", "ons", "ons_corrigido"],
            "somas": ["real", "persistencia", "ons_ant", "ons_ant_corrigido", "ons_ant_semana", "media_ridge_gbm", "media_com_ons_ant_semana", "ons", "ons_corrigido"],
            "renomear": {"media_ridge_gbm": "pecas_ml", "media_com_ons_ant_semana": "pecas_ml_com_ons_ant_semana"},
            "modelos": ["ons_ant", "ons_ant_corrigido", "ons_ant_semana", "persistencia", "pecas_ml", "pecas_escolhidas", "pecas_ml_com_ons_ant_semana",
                        "ons_corrigido", "ons"],
            "testes": [("pecas_escolhidas", "ons_ant_semana"), ("pecas_ml", "ons_ant_semana"), ("ons_ant_semana", "ons_ant_corrigido"), ("ons_ant_corrigido", "ons_ant"),
                       ("pecas_escolhidas", "ons_corrigido")],
            "regua": "ons_ant_semana"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--horizonte", type=int, default=1, help="1 = D+1, 2 = D+2...")
    parser.add_argument("--ate", type=pd.Timestamp, help="last backtest day (YYYY-MM-DD), to reproduce a past run")
    args = parser.parse_args()
    horizonte = args.horizonte
    cfg = configuracao(horizonte)
    base, candidatos = cfg["base"], cfg["candidatos"]
    con = conectar()
    balanco = carregar_balanco_horario(con)
    dessem = carregar_dessem(con)
    con.close()
    # The last day of the balance often comes out incomplete (seen on 2026-11-09 in the Northeast): left out.
    ultimo = balanco["instante"].max().normalize() - pd.Timedelta(days=2)
    if args.ate is not None:
        ultimo = min(ultimo, args.ate)
    balanco = balanco[balanco["instante"] < ultimo + pd.Timedelta(days=1)]
    pecas = backtest_pecas(balanco, dessem, carregar_previsao_renovaveis(horizonte + 1), carregar_temperatura_prevista(horizonte + 1),
                           folds_trimestrais(2025, ultimo), horizonte=horizonte)
    pecas = pecas.dropna(subset=["ons", "ons_ant", "real", "persistencia"])
    for _, g in pecas.groupby(["peca", "subsistema"]):
        # ons_corrigido is the D+1-world one (errors up to T−2); ons_ant_corrigido only uses errors known at decision time.
        pecas.loc[g.index, "ons_corrigido"] = corrigir_vies(g).clip(lower=0)
        pecas.loc[g.index, "ons_ant_corrigido"] = corrigir_vies(g, coluna="ons_ant", gap=horizonte + 1).clip(lower=0)
        pecas.loc[g.index, "ons_ant_semana"] = corrigir_vies_semana(g, coluna="ons_ant", gap=horizonte + 1).clip(lower=0)
    pecas = pecas.dropna(subset=["ons_corrigido", "ons_ant_corrigido", "ons_ant_semana"])
    escolhas, resultados_pecas = {}, {}
    for peca, g in pecas.groupby("peca"):
        idx = g.index
        ml = g[["ridge", "gbm"]].mean(axis=1)
        pecas.loc[idx, "media_com_ons"] = ml * 0.5 + g["ons"] * 0.5
        pecas.loc[idx, "media_com_ons_corrigido"] = ml * 0.5 + g["ons_corrigido"] * 0.5
        pecas.loc[idx, "media_com_ons_ant_corrigido"] = ml * 0.5 + g["ons_ant_corrigido"] * 0.5
        pecas.loc[idx, "media_com_ons_ant_semana"] = ml * 0.5 + g["ons_ant_semana"] * 0.5
        g = pecas.loc[idx]
        desenvolvimento = g[g["data"] < INICIO_CONFIRMACAO].dropna(subset=candidatos)
        escolhido = min(candidatos, key=lambda c: mae(desenvolvimento, c))
        escolhas[peca] = escolhido
        confirmacao = g[g["data"] >= INICIO_CONFIRMACAO].dropna(subset=candidatos)
        colunas = list(dict.fromkeys([base] + cfg["referencias"] + candidatos))
        resultados_pecas[peca] = {"escolhido_em_2025": escolhido,
                                  "desenvolvimento_2025": resumo(desenvolvimento, colunas, base=base),
                                  "confirmacao_2026": resumo(confirmacao, colunas, base=base),
                                  "teste_2026": intervalo(confirmacao, escolhido, base)}
    valores = list(dict.fromkeys(cfg["somas"] + candidatos))
    largura = pecas.pivot_table(index=["subsistema", "data", "hora"], columns="peca", values=valores)
    largura.columns = [f"{m}_{p}" for m, p in largura.columns]
    largura = largura.dropna().reset_index()
    liquida = largura[["subsistema", "data", "hora"]].copy()
    for nome in cfg["somas"]:
        liquida[nome] = sum(s * largura[f"{nome}_{p}"] for p, s in SINAIS)
    # Per-component choice made on 2025: the "recipe" a desk would freeze before looking at 2026.
    liquida["pecas_escolhidas"] = sum(s * largura[f"{escolhas[p]}_{p}"] for p, s in SINAIS)
    liquida = liquida.rename(columns=cfg["renomear"])
    modelos = cfg["modelos"]
    sin = liquida.groupby(["data", "hora"]).filter(lambda g: len(g) == 4).groupby(["data", "hora"])[["real"] + modelos].sum().reset_index()
    conf, conf_sin = liquida[liquida["data"] >= INICIO_CONFIRMACAO], sin[sin["data"] >= INICIO_CONFIRMACAO]
    conf_sin = conf_sin.assign(faixa=conf_sin["hora"].map(faixa_horaria))

    def amplitude(frame, coluna):
        return frame.groupby("data")[coluna].agg(lambda s: s.max() - s.min())

    resultado = {
        "horizonte": f"D+{horizonte}", "regua": cfg["regua"],
        "periodo": [str(pecas["data"].min().date()), str(pecas["data"].max().date())], "escolhas": escolhas, "pecas": resultados_pecas,
        "liquida_subsistemas_2026": {s: resumo(g, modelos, base=base) for s, g in conf.groupby("subsistema")},
        "liquida_sin_2025": resumo(sin[sin["data"] < INICIO_CONFIRMACAO], modelos, base=base),
        "liquida_sin_2026": resumo(conf_sin, modelos, base=base),
        "liquida_sin_2026_por_faixa": {f: resumo(g, modelos, base=base) for f, g in conf_sin.groupby("faixa")},
        "liquida_sin_2026_por_mes": {str(m): resumo(g, modelos, base=base) for m, g in conf_sin.groupby(conf_sin["data"].dt.month)},
        "testes_sin_2026": [intervalo(conf_sin, a, b) for a, b in cfg["testes"]],
        "testes_subsistemas_2026": {s: intervalo(g, "pecas_escolhidas", cfg["regua"]) for s, g in conf.groupby("subsistema")},
        "rampa_sin_2026": {m: round(float((amplitude(conf_sin, m) - amplitude(conf_sin, "real")).abs().mean()), 1) for m in modelos},
    }
    if horizonte > 1:
        # How close we get to the schedule ONS will only publish later (the input to that day's price).
        resultado["antecipa_programacao_sin_2026"] = resumo(conf_sin, ["ons_ant", "ons_ant_corrigido", "ons_ant_semana", "pecas_ml", "pecas_escolhidas"], alvo="ons", base="ons_ant")
    sufixo = "" if horizonte == 1 else f"_dmais{horizonte}"
    destino = Path(__file__).resolve().parents[1] / f"docs/inventory/carga_liquida{sufixo}_results.json"
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pecas.to_parquet(DATA_DIR / f"gold/previsoes_carga_liquida{sufixo}.parquet", index=False)
    print(json.dumps({k: resultado[k] for k in ("horizonte", "escolhas", "liquida_sin_2025", "liquida_sin_2026", "testes_sin_2026")}, ensure_ascii=False, indent=1))
    return 0 if np.isfinite(conf_sin["real"]).all() else 1


if __name__ == "__main__":
    raise SystemExit(main())
