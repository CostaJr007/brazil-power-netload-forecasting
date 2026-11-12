"""Maiores usinas solares (ONS) e incidência solar nas coordenadas delas (NASA POWER).

Gera docs/inventory/solar_usinas.json: ranking, sazonalidade e quanto a radiação explica a geração.
Radiação aqui é OBSERVADA por satélite/reanálise: mede a física, não é previsão.
Dados NASA POWER são públicos; as respostas ficam na Bronze.

Executar: .\\.venv\\Scripts\\python.exe scripts/solar_usinas.py
"""
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire import DATA_DIR, ROOT, Store, resolve_data_path  # noqa: E402
from models.dados import conectar  # noqa: E402

N_USINAS = 12
INICIO = date(2021, 1, 1)
URL = "https://power.larc.nasa.gov/api/temporal/hourly/point?"
# Usa só horas em que a usina já estava com quase toda a capacidade atual.
FRACAO_CAPACIDADE = 0.95
FIM_TREINO = pd.Timestamp("2025-01-01")


def ranking(con):
    return con.sql("""
        WITH base AS (
            SELECT nom_usina_conjunto AS usina, any_value(id_estado) AS uf, any_value(id_subsistema) AS subsistema,
                   avg(coalesce(val_latitudesecoletora, val_latitudepontoconexao)) AS lat,
                   avg(coalesce(val_longitudesecoletora, val_longitudepontoconexao)) AS lon,
                   max(_event_time_source) AS ultimo
            FROM silver_fator_capacidade_2 WHERE nom_tipousina = 'Solar' GROUP BY 1),
        ultimo AS (
            SELECT s.nom_usina_conjunto AS usina, sum(s.val_capacidadeinstalada) AS capacidade_mw
            FROM silver_fator_capacidade_2 s JOIN base b ON s.nom_usina_conjunto = b.usina AND s._event_time_source = b.ultimo
            WHERE s.nom_tipousina = 'Solar' GROUP BY 1),
        ano AS (
            SELECT nom_usina_conjunto AS usina, sum(val_geracaoverificada) / nullif(sum(val_capacidadeinstalada), 0) AS fator_12m,
                   sum(val_geracaoverificada) / 1000.0 AS gwh_12m
            FROM silver_fator_capacidade_2
            WHERE nom_tipousina = 'Solar' AND _event_time_source >= (SELECT max(_event_time_source) - INTERVAL 365 DAY FROM silver_fator_capacidade_2)
            GROUP BY 1)
        SELECT b.usina, b.uf, b.subsistema, round(b.lat, 3) AS lat, round(b.lon, 3) AS lon, round(u.capacidade_mw, 1) AS capacidade_mw,
               round(a.fator_12m * 100, 1) AS fator_capacidade_12m_pct, round(a.gwh_12m) AS gwh_12m
        FROM base b JOIN ultimo u USING (usina) LEFT JOIN ano a USING (usina)
        WHERE b.lat IS NOT NULL ORDER BY u.capacidade_mw DESC""").df()


def geracao(con, usina):
    nome = usina.replace("'", "''")
    frame = con.sql(f"""SELECT _event_time_source AS instante, sum(val_geracaoverificada) AS geracao, sum(val_capacidadeinstalada) AS capacidade
                        FROM silver_fator_capacidade_2 WHERE nom_tipousina = 'Solar' AND nom_usina_conjunto = '{nome}' GROUP BY 1 ORDER BY 1""").df()
    frame["instante"] = pd.to_datetime(frame["instante"])
    return frame.set_index("instante")


def baixar_radiacao(store, usina, lat, lon, fim):
    consulta = urlencode({"parameters": "ALLSKY_SFC_SW_DWN,CLRSKY_SFC_SW_DWN", "community": "RE", "longitude": lon, "latitude": lat,
                          "start": INICIO.strftime("%Y%m%d"), "end": fim.strftime("%Y%m%d"), "format": "JSON", "time-standard": "UTC"})
    recurso = "".join(c if c.isalnum() else "_" for c in usina)[:60]
    for tentativa in range(1, 5):
        try:
            manifesto = store.fetch("nasa_power", "hourly_point_solar", recurso, URL + consulta, context={"role": "reanalysis_satellite", "usina": usina})
            corpo = json.loads(Path(resolve_data_path(manifesto["path"])).read_text(encoding="utf-8"))["properties"]["parameter"]
            break
        except (json.JSONDecodeError, KeyError, OSError) as erro:
            if tentativa == 4:
                raise
            print(f"{usina}: {type(erro).__name__}, nova tentativa", flush=True)
            time.sleep(30)
    frame = pd.DataFrame({"ghi": corpo["ALLSKY_SFC_SW_DWN"], "ghi_ceu_limpo": corpo["CLRSKY_SFC_SW_DWN"]})
    frame.index = pd.to_datetime(frame.index, format="%Y%m%d%H")
    return frame.where(frame >= 0)  # POWER usa -999 para ausente.


def melhor_defasagem(fc, ghi):
    """Confere o fuso empiricamente: desloca a radiação e fica com a maior correlação."""
    resultados = {}
    for horas in range(-6, 7):
        unido = pd.concat([fc, ghi.shift(horas, freq="h")], axis=1, join="inner").dropna()
        if len(unido) > 1000:
            resultados[horas] = float(unido.iloc[:, 0].corr(unido.iloc[:, 1]))
    return (max(resultados, key=resultados.get), resultados) if resultados else (None, resultados)


def analisar_usina(gen, rad):
    gen = gen[(gen["capacidade"] > 0) & (gen["capacidade"] >= FRACAO_CAPACIDADE * gen["capacidade"].iloc[-1])]
    fc = (gen["geracao"] / gen["capacidade"]).rename("fc").clip(0, 1.3)
    deslocamento, _ = melhor_defasagem(fc, rad["ghi"])
    if deslocamento is None:
        return None
    rad = rad.shift(deslocamento, freq="h")
    d = pd.concat([fc, rad], axis=1, join="inner").dropna()
    if len(d) < 2000:
        return None
    dia = d[d["ghi_ceu_limpo"] > 50].copy()
    dia["mes"], dia["hora"] = dia.index.month, dia.index.hour
    treino, teste = dia[dia.index < FIM_TREINO], dia[dia.index >= FIM_TREINO]
    if len(treino) < 500 or len(teste) < 500:
        return None
    # Razão pela origem: sem sol, sem geração. Modelo físico simples, com um coeficiente.
    b = float((treino["ghi"] * treino["fc"]).sum() / (treino["ghi"] ** 2).sum())
    clima = treino.groupby(["mes", "hora"])["fc"].mean().rename("clima")
    teste = teste.join(clima, on=["mes", "hora"]).dropna(subset=["clima"])
    erro_rad = (teste["fc"] - b * teste["ghi"]).abs().mean()
    erro_clima = (teste["fc"] - teste["clima"]).abs().mean()
    return {"horas_diurnas_teste": len(teste), "deslocamento_h": int(deslocamento),
            "correlacao_diurna": round(float(teste["fc"].corr(teste["ghi"])), 3),
            "mae_fc_radiacao": round(float(erro_rad), 4), "mae_fc_climatologia": round(float(erro_clima), 4),
            "skill_radiacao_vs_climatologia": round(float(1 - erro_rad / erro_clima), 3)}, d


def main():
    con = conectar()
    tabela = ranking(con)
    fim = date.today() - timedelta(days=10)  # Componentes de satélite chegam com alguns dias de atraso.
    store, por_usina, mensal = Store(DATA_DIR), [], []
    try:
        for linha in tabela.itertuples():
            if len(mensal) == N_USINAS:
                break
            rad = baixar_radiacao(store, linha.usina, linha.lat, linha.lon, fim)
            analise = analisar_usina(geracao(con, linha.usina), rad)
            time.sleep(2)
            if analise is None:
                por_usina.append({"usina": linha.usina, "aviso": "histórico insuficiente com a capacidade atual"})
                continue
            resumo, dados = analise
            por_usina.append({"usina": linha.usina, "uf": linha.uf, **resumo})
            mensal.append(dados.assign(usina=linha.usina, uf=linha.uf))
            print(linha.usina, resumo, flush=True)
    finally:
        store.close()
        con.close()
    todos = pd.concat(mensal)
    todos["mes"], todos["hora"] = todos.index.month, todos.index.hour
    # Médias diárias: 24 h × média horária (W/m²) / 1000 = kWh/m²/dia.
    grupo = todos.groupby("mes")
    sazonal = pd.DataFrame({"ghi_kwh_m2_dia": grupo["ghi"].mean() * 24 / 1000, "ceu_limpo_kwh_m2_dia": grupo["ghi_ceu_limpo"].mean() * 24 / 1000,
                            "indice_claridade": grupo["ghi"].sum() / grupo["ghi_ceu_limpo"].sum(), "fator_capacidade_pct": grupo["fc"].mean() * 100}).round(3)
    pico = todos[todos["ghi_ceu_limpo"] > 50].groupby(["mes", "hora"])["fc"].mean().reset_index()
    horas_uteis = pico[pico["fc"] >= 0.05].groupby("mes")["hora"].agg(["min", "max"])
    resultado = {"ranking_top20": tabela.head(20).to_dict(orient="records"), "total_usinas": len(tabela),
                 "capacidade_total_mw": round(float(tabela["capacidade_mw"].sum())),
                 "capacidade_por_uf_mw": tabela.groupby("uf")["capacidade_mw"].sum().sort_values(ascending=False).round().to_dict(),
                 "por_usina": por_usina, "sazonal_por_mes": sazonal.reset_index().to_dict(orient="records"),
                 "janela_producao_por_mes": horas_uteis.reset_index().to_dict(orient="records")}
    (ROOT / "docs/inventory/solar_usinas.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=float) + "\n", encoding="utf-8")
    print(json.dumps({k: resultado[k] for k in ("total_usinas", "capacidade_total_mw", "capacidade_por_uf_mw")}, ensure_ascii=False, indent=1))
    print(sazonal.to_string())
    print(pd.DataFrame(por_usina).to_string())
    print(tabela.head(20).to_string())
    return 0 if np.isfinite(sazonal["ghi_kwh_m2_dia"]).all() else 1


if __name__ == "__main__":
    raise SystemExit(main())
