"""Irradiância medida nas maiores usinas solares (ONS) e efeito dos cortes de geração.

Usa restricao_coff_fotovoltaica_detail: irradiância da própria usina, geração verificada, geração de
referência (o que produziria sem corte) e o indicador de hora restrita. Grava docs/inventory/solar_irradiancia.json.

Executar: .\\.venv\\Scripts\\python.exe scripts/solar_irradiancia.py
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from models.dados import conectar  # noqa: E402
from solar_usinas import ranking  # noqa: E402

N_USINAS = 12
FIM_TREINO = pd.Timestamp("2026-01-01")
LIMIAR_DIA = 20.0  # W/m²: abaixo disso consideramos noite.


def carregar(con, usinas):
    nomes = ", ".join("'" + u.replace("'", "''") + "'" for u in usinas)
    frame = con.sql(f"""
        WITH meia AS (
            SELECT nom_conjuntousina AS usina, _event_time_source AS instante,
                   avg(val_irradianciaverificado) FILTER (flg_dadoirradianciainvalido = 0) AS irradiancia,
                   sum(val_geracaoverificada) AS geracao, sum(val_geracaoreferenciafinal) AS referencia,
                   max(flg_geracaorestrita) AS restrita
            FROM silver_restricao_coff_fotovoltaica_detail
            WHERE nom_conjuntousina IN ({nomes})
            GROUP BY 1, 2)
        SELECT usina, date_trunc('hour', instante) AS instante, avg(irradiancia) AS irradiancia, avg(geracao) AS geracao,
               avg(referencia) AS referencia, max(restrita) AS restrita
        FROM meia GROUP BY 1, 2 ORDER BY 1, 2""").df()
    frame["instante"] = pd.to_datetime(frame["instante"])
    return frame


def analisar(d, capacidade):
    d = d[(d["irradiancia"] > LIMIAR_DIA) & d["geracao"].notna()].copy()
    if len(d) < 500:
        return None
    d["fc"] = d["geracao"] / capacidade
    d["mes"], d["hora"] = d["instante"].dt.month, d["instante"].dt.hour
    livre = d[d["restrita"] == 0]
    treino, teste = livre[livre["instante"] < FIM_TREINO], livre[livre["instante"] >= FIM_TREINO]
    saida = {"horas_diurnas": len(d), "inicio": str(d["instante"].min().date()), "pct_horas_com_corte": round(float((d["restrita"] > 0).mean() * 100), 1),
             "correlacao_todas_as_horas": round(float(d["fc"].corr(d["irradiancia"])), 3),
             "correlacao_sem_corte": round(float(livre["fc"].corr(livre["irradiancia"])), 3)}
    if len(treino) < 300 or len(teste) < 100:
        return saida
    # Física simples: proporcional à irradiância até o limite do inversor. Parâmetros só com o treino.
    baixa = treino[treino["irradiancia"] < 600]
    b = float((baixa["irradiancia"] * baixa["fc"]).sum() / (baixa["irradiancia"] ** 2).sum())
    teto = float(treino["fc"].quantile(0.995))
    clima = treino.groupby(["mes", "hora"])["fc"].mean().rename("clima")
    teste = teste.join(clima, on=["mes", "hora"]).dropna(subset=["clima"])
    previsto = (b * teste["irradiancia"]).clip(upper=teto)
    erro_medido, erro_clima = (teste["fc"] - previsto).abs().mean(), (teste["fc"] - teste["clima"]).abs().mean()
    return saida | {"mae_fc_com_irradiancia": round(float(erro_medido), 4), "mae_fc_climatologia": round(float(erro_clima), 4),
                    "skill_vs_climatologia": round(float(1 - erro_medido / erro_clima), 3), "horas_teste": len(teste)}


def main():
    con = conectar()
    tabela = ranking(con)
    disponiveis = {r[0] for r in con.sql("SELECT DISTINCT nom_conjuntousina FROM silver_restricao_coff_fotovoltaica_detail").fetchall()}
    tabela = tabela[tabela["usina"].isin(disponiveis)].head(N_USINAS)
    dados = carregar(con, tabela["usina"].tolist())
    con.close()
    capacidades = tabela.set_index("usina")["capacidade_mw"]
    por_usina = [{"usina": u, "uf": tabela.set_index("usina").loc[u, "uf"], "capacidade_mw": float(capacidades[u]), **(analisar(g, capacidades[u]) or {"aviso": "poucas horas"})}
                 for u, g in dados.groupby("usina")]
    dia = dados[(dados["irradiancia"] > LIMIAR_DIA) & dados["geracao"].notna()].copy()
    dia["ano_mes"], dia["mes"], dia["hora"] = dia["instante"].dt.strftime("%Y-%m"), dia["instante"].dt.month, dia["instante"].dt.hour
    # A referência só vem preenchida em parte das horas (em geral as com corte): a razão abaixo NÃO é a perda anual.
    dia = dia.assign(perda=(dia["referencia"] - dia["geracao"]).clip(lower=0).where(dia["referencia"].notna()))
    def sumario(grupo):
        return pd.Series({"irradiancia_media_w_m2": grupo["irradiancia"].mean(), "pct_horas_com_corte": (grupo["restrita"] > 0).mean() * 100,
                          "corte_pct_da_referencia_quando_informada": grupo["perda"].sum() / grupo["referencia"].sum() * 100})
    # Só anos completos para a sazonalidade; o histórico começa no meio de 2024.
    completo = dia[dia["instante"].dt.year == 2025]
    resultado = {"por_usina": por_usina, "periodo": [str(dia["instante"].min().date()), str(dia["instante"].max().date())],
                 "por_ano_mes": dia.groupby("ano_mes").apply(sumario, include_groups=False).round(2).reset_index().to_dict(orient="records"),
                 "sazonal_2025_por_mes": completo.groupby("mes").apply(sumario, include_groups=False).round(2).reset_index().to_dict(orient="records"),
                 "por_hora": dia.groupby("hora").apply(sumario, include_groups=False).round(2).reset_index().to_dict(orient="records")}
    destino = Path(__file__).resolve().parents[1] / "docs/inventory/solar_irradiancia.json"
    destino.write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=float) + "\n", encoding="utf-8")
    print(json.dumps(resultado, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()
