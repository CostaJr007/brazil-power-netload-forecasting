"""Camada de BI: tabelas em modelo estrela (Parquet) para o Power BI, em data/bi/.

Fatos (um por pergunta de negócio) e dimensões compartilhadas (data, hora, subsistema):
  fato_carga_liquida  backtest horário D+1 e D+2: previsto, real, régua, ONS e banda de 80% (walk-forward)
  fato_pecas          o mesmo por peça (carga, eólica, solar), para ver de onde vem o erro
  fato_previsao       previsão operacional (cada decisão), com banda de 80%
  fato_auditoria      replay da semana auditada, como se fossem 22h da véspera
  fato_painel_diario  balanço diário do SIN (carga, renováveis, hidro, térmica, ENA, EAR, CMO, PLD estimado)
  fato_pld_diario / fato_ear_diario / fato_ena_bacia   séries diárias por subsistema ou bacia
  dim_data / dim_hora / dim_subsistema / info_execucao

Sem rede: lê os resultados já gerados e as views Gold. O projeto Power BI (bi/) aponta para esta pasta.
Executar: .\\.venv\\Scripts\\python.exe scripts/exportar_bi.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire import DATA_DIR  # noqa: E402
from models.carga import calendario  # noqa: E402
from models.dados import conectar  # noqa: E402
from models.operacional import banda_walk_forward, carga_liquida, historico_liquido  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = DATA_DIR / "bi"
HORIZONTES = {"D+1": ("previsoes_carga_liquida", "carga_liquida_results.json", "ons"),
              "D+2": ("previsoes_carga_liquida_dmais2", "carga_liquida_dmais2_results.json", "ons_ant_semana")}
INICIO_BANDA = pd.Timestamp("2025-10-01")      # 120 dias de erros acumulados antes da primeira banda
INICIO_CONFIRMACAO = pd.Timestamp("2026-01-01")
# O BI sai em inglês (portfólio): nomes de tabelas, colunas e valores traduzidos só na gravação.
SUBSISTEMAS = [("SIN", "National grid (SIN)", 0), ("SE", "Southeast/Center-West", 1), ("S", "South", 2),
               ("NE", "Northeast", 3), ("N", "North", 4)]
NOMES_MES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DIAS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TABELAS_EN = {"fato_carga_liquida": "fact_net_load", "fato_pecas": "fact_components", "fato_previsao": "fact_forecast",
              "fato_auditoria": "fact_audit", "fato_painel_diario": "fact_system_daily", "fato_pld_diario": "fact_price_daily",
              "fato_ear_diario": "fact_storage_daily", "fato_ena_bacia": "fact_inflow_basin", "dim_data": "dim_date",
              "dim_hora": "dim_hour", "dim_subsistema": "dim_subsystem", "info_execucao": "run_info"}
COLUNAS_EN = {"subsistema": "subsystem", "data": "date", "hora": "hour", "previsto": "forecast", "real": "actual", "regua": "benchmark",
              "ons": "ons_schedule", "banda_inf": "band_low", "banda_sup": "band_high", "horizonte": "horizon", "periodo": "period",
              "instante": "timestamp", "peca": "component", "decisao": "decision_date", "passo": "step", "horas": "hours",
              "carga_mwmed": "load_mw", "eolica_mwmed": "wind_mw", "solar_mwmed": "solar_mw", "hidraulica_mwmed": "hydro_mw",
              "termica_mwmed": "thermal_mw", "carga_liquida_mwmed": "net_load_mw", "rampa_carga_liquida_mwmed": "net_load_ramp_mw",
              "ena_mwmed": "inflow_mw", "ena_pct_mlt": "inflow_pct_ltm", "ear_pct": "storage_pct", "ear_mwmes": "storage_mwmonth",
              "corte_eolica_mwmed": "wind_curtailment_mw", "corte_solar_mwmed": "solar_curtailment_mw", "pld_estimado_se": "price_est_se",
              "pld_estimado": "price_est", "teto_estrutural_aplicado": "structural_cap_applied", "bacia": "basin",
              "ena_bruta_mwmed": "inflow_mw", "ena_bruta_pct_mlt": "inflow_pct_ltm", "ano": "year", "mes": "month",
              "nome_mes": "month_name", "ano_mes": "year_month", "trimestre": "quarter", "semana_iso": "iso_week",
              "dia_semana_num": "weekday_num", "dia_semana": "weekday", "fim_de_semana": "is_weekend", "feriado": "is_holiday",
              "tipo_dia": "day_type", "hora_texto": "hour_label", "faixa": "day_part", "nome": "name", "ordem": "sort_order",
              "gerado_em": "generated_at", "receita_d1": "recipe_d1", "receita_d2": "recipe_d2", "regua_d1": "benchmark_d1",
              "regua_d2": "benchmark_d2", "falha_telemetria": "telemetry_outage"}
PECAS_EN = {"carga": "load", "eolica": "wind", "solar": "solar"}


def ler(nome):
    return json.loads((RAIZ / f"docs/inventory/{nome}").read_text(encoding="utf-8"))


def periodo(datas):
    return pd.Series(datas).lt(INICIO_CONFIRMACAO).map({True: "selection (2025)", False: "validation (2026)"}).values


def fatos_backtest():
    liquidas, pecas, info = [], [], {}
    for horizonte, (arquivo, resultados, regua) in HORIZONTES.items():
        p = pd.read_parquet(DATA_DIR / f"gold/{arquivo}.parquet")
        escolhas = ler(resultados)["escolhas"]
        info[horizonte] = {"receitas": escolhas, "regua": regua}
        liq = historico_liquido(p, escolhas, regua)
        liq = liq.merge(carga_liquida(p, "ons").rename(columns={"ons": "ons"}), on=["subsistema", "data", "hora"], how="left")
        liq = banda_walk_forward(liq, INICIO_BANDA).merge(liq, how="right")  # banda só a partir de out/2025
        liquidas.append(liq.assign(horizonte=horizonte))
        q = p.assign(previsto=float("nan"))
        for peca, receita in escolhas.items():
            q.loc[q["peca"] == peca, "previsto"] = q.loc[q["peca"] == peca, receita]
        pecas.append(q[["subsistema", "data", "hora", "peca", "previsto", "real", regua]].rename(columns={regua: "regua"})
                     .dropna(subset=["previsto", "real"]).assign(horizonte=horizonte))
    liq = pd.concat(liquidas, ignore_index=True)
    liq["periodo"] = periodo(liq["data"])
    pec = pd.concat(pecas, ignore_index=True)
    pec["periodo"] = periodo(pec["data"])
    return liq, pec, info


def dias_falha_telemetria(pec, limite=0.15, minimo_mw=1000, horas=6):
    """Dias em que o balanço do ONS perdeu usinas: eólica/solar verificada < 15% da programação do próprio ONS
    (com programação > 1 GW) em 6+ horas de um subsistema. Detectado em D+1, onde a régua é a programação do dia.
    Ex.: 16/01, 07/03 e 09/05/2026, eólica do NE com 0,2–0,5 GW contra ~12 GW programados."""
    r = pec[(pec["horizonte"] == "D+1") & pec["peca"].isin(["eolica", "solar"])]
    suspeitas = r[(r["real"] < limite * r["regua"]) & (r["regua"] > minimo_mw)]
    contagem = suspeitas.groupby(["subsistema", "data"]).size()
    return set(contagem[contagem >= horas].index.get_level_values("data"))


def fato_previsao():
    arquivo = DATA_DIR / "gold/previsao_operacional_liquida.parquet"
    if not arquivo.exists():
        return pd.DataFrame(columns=["decisao", "data", "hora", "subsistema", "previsto", "banda_inf", "banda_sup", "regua", "horizonte", "passo"])
    f = pd.read_parquet(arquivo).rename(columns={"ons_ant_semana": "regua"})
    return f.assign(horizonte="D+" + f["horizonte"].astype(str), passo="D+" + f["passo"].astype(str))


def fato_auditoria():
    arquivo = DATA_DIR / "gold/auditoria_previsoes.parquet"
    if not arquivo.exists():
        return pd.DataFrame()
    a = pd.read_parquet(arquivo)
    partes = []
    for passo, g in a.groupby("passo"):
        regua = "ons" if passo == 1 else "ons_ant_semana"
        f = carga_liquida(g, "previsto")
        for coluna in ("real", regua):
            f = f.merge(carga_liquida(g, coluna), on=["subsistema", "data", "hora"], how="left")
        partes.append(f.rename(columns={regua: "regua"}).dropna(subset=["previsto", "real"]).assign(passo=f"D+{passo}"))
    return pd.concat(partes, ignore_index=True)


def views_gold():
    con = conectar()
    try:
        sql = {"fato_painel_diario": "SELECT * EXCLUDE (fontes_ausentes) FROM vw_painel_energia_diario",
               "fato_pld_diario": "SELECT subsistema, data_referencia, pld_estimado, teto_estrutural_aplicado FROM vw_pld_estimado_diario",
               "fato_ear_diario": "SELECT subsistema, data_referencia, ear_pct, ear_mwmes FROM vw_ear_subsistema_diaria",
               "fato_ena_bacia": "SELECT nom_bacia AS bacia, data_referencia, ena_bruta_mwmed, ena_bruta_pct_mlt FROM vw_ena_bacia_diaria"}
        saida = {}
        for nome, consulta in sql.items():
            f = con.sql(consulta).df().rename(columns={"data_referencia": "data"})
            f["data"] = pd.to_datetime(f["data"])
            saida[nome] = f
        return saida
    finally:
        con.close()


def dimensoes(datas):
    dias = pd.date_range(min(datas), max(datas), freq="D")
    cal = calendario(dias)
    dim_data = pd.DataFrame({"data": dias, "ano": dias.year, "mes": dias.month, "nome_mes": [NOMES_MES[m - 1] for m in dias.month],
                             "ano_mes": dias.strftime("%Y-%m"), "trimestre": "Q" + dias.quarter.astype(str),
                             "semana_iso": dias.isocalendar().week.astype(int).values, "dia_semana_num": dias.day_of_week + 1,
                             "dia_semana": [DIAS[d] for d in dias.day_of_week],
                             "fim_de_semana": dias.day_of_week >= 5, "feriado": cal["feriado"].astype(bool).values,
                             "tipo_dia": "weekday"})
    dim_data.loc[dim_data["fim_de_semana"], "tipo_dia"] = "weekend"
    dim_data.loc[dim_data["feriado"], "tipo_dia"] = "holiday"
    faixas = {**{h: "overnight" for h in range(0, 6)}, **{h: "morning" for h in range(6, 12)}, **{h: "afternoon" for h in range(12, 18)},
              **{h: "peak" for h in range(18, 22)}, 22: "evening", 23: "evening"}
    dim_hora = pd.DataFrame({"hora": range(24), "hora_texto": [f"{h:02d}:00" for h in range(24)], "faixa": [faixas[h] for h in range(24)]})
    dim_sub = pd.DataFrame(SUBSISTEMAS, columns=["subsistema", "nome", "ordem"])
    return dim_data, dim_hora, dim_sub


def main():
    DESTINO.mkdir(parents=True, exist_ok=True)
    liq, pec, info = fatos_backtest()
    falhas = dias_falha_telemetria(pec)
    print(f"Dias com falha de telemetria no balanço do ONS: {sorted(str(d.date()) for d in falhas)}")
    liq["falha_telemetria"] = liq["data"].isin(falhas)
    pec["falha_telemetria"] = pec["data"].isin(falhas)
    tabelas = {"fato_carga_liquida": liq, "fato_pecas": pec, "fato_previsao": fato_previsao(), "fato_auditoria": fato_auditoria(), **views_gold()}
    datas = pd.concat([t["data"] for t in tabelas.values() if len(t)])
    dim_data, dim_hora, dim_sub = dimensoes(datas)
    tabelas.update({"dim_data": dim_data, "dim_hora": dim_hora, "dim_subsistema": dim_sub})
    tabelas["info_execucao"] = pd.DataFrame([{"gerado_em": datetime.now().isoformat(timespec="seconds"),
                                              "receita_d1": json.dumps(info["D+1"]["receitas"], ensure_ascii=False),
                                              "receita_d2": json.dumps(info["D+2"]["receitas"], ensure_ascii=False),
                                              "regua_d1": "ONS day-ahead schedule (DESSEM)",
                                              "regua_d2": "previous-day ONS schedule, bias-corrected by hour and weekday"}])
    for nome in ("fato_previsao", "fato_auditoria", "fato_carga_liquida"):   # eixo contínuo hora a hora nos gráficos
        t = tabelas[nome]
        if len(t):
            t["instante"] = pd.to_datetime(t["data"]) + pd.to_timedelta(t["hora"], unit="h")
    tabelas["fato_pecas"]["peca"] = tabelas["fato_pecas"]["peca"].map(PECAS_EN)
    for nome, tabela in list(tabelas.items()):
        tabela = tabela.rename(columns=COLUNAS_EN)
        nome = TABELAS_EN[nome]
        for c in tabela.columns:
            if pd.api.types.is_datetime64_any_dtype(tabela[c]):
                tabela[c] = tabela[c].astype("datetime64[ms]")   # Power BI lê datas em ms sem problema
        tabela.to_parquet(DESTINO / f"{nome}.parquet", index=False)
        print(f"{nome:22s} {len(tabela):>9,} linhas  {list(tabela.columns)}")
    print(f"\nPasta: {DESTINO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
