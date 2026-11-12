"""Previsão operacional: escolhe o horizonte pelo que já foi publicado e soma as peças corretamente."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np  # noqa: E402
from models.operacional import (  # noqa: E402
    aplicar_banda, aplicar_receitas, banda_walk_forward, carga_liquida, dias_completos, estender_balanco, horizonte_efetivo, quantis_residuo)

D = pd.Timestamp("2026-11-12")
DIA = pd.Timedelta(days=1)


def test_horizonte_d1_quando_tudo_saiu():
    assert horizonte_efetivo(D + DIA, {D - DIA}, {D, D + DIA}) == 1


def test_sem_balanco_de_ontem_usa_d2_e_depois_de_amanha_fica_sem_previsao():
    verificados, programados = {D - 2 * DIA}, {D}
    assert horizonte_efetivo(D + DIA, verificados, programados) == 2
    assert horizonte_efetivo(D + 2 * DIA, verificados, programados) is None


def test_sem_dessem_de_amanha_usa_d2():
    assert horizonte_efetivo(D + DIA, {D - DIA}, {D}) == 2


def test_dias_completos_exige_os_quatro_subsistemas():
    horas = pd.date_range(D - DIA, periods=48, freq="h")
    frame = pd.concat([pd.DataFrame({"subsistema": s, "instante": horas, "carga": 1.0}) for s in ("N", "NE", "S", "SE")])
    frame.loc[(frame["subsistema"] == "NE") & (frame["instante"] >= D + pd.Timedelta(hours=20)), "carga"] = None
    assert dias_completos(frame, "carga") == {D - DIA}


def test_estender_balanco_cria_horas_vazias_ate_o_fim_do_alvo():
    horas = pd.date_range(D - DIA, periods=24, freq="h")
    frame = pd.DataFrame({"subsistema": "N", "instante": horas, "carga": 1.0, "eolica": 0.0, "solar": 0.0})
    estendido = estender_balanco(frame, D + 2 * DIA)
    assert estendido["instante"].max() == D + 2 * DIA - pd.Timedelta(hours=1)
    assert estendido.loc[estendido["instante"] >= D, "carga"].isna().all()


def test_carga_liquida_e_carga_menos_renovaveis_e_sin_soma_os_quatro():
    linhas = [{"subsistema": s, "data": D, "hora": 0, "peca": p, "previsto": v}
              for s in ("N", "NE", "S", "SE") for p, v in (("carga", 100.0), ("eolica", 30.0), ("solar", 10.0))]
    liquida = carga_liquida(pd.DataFrame(linhas))
    assert (liquida.loc[liquida["subsistema"] != "SIN", "previsto"] == 60.0).all()
    assert liquida.loc[liquida["subsistema"] == "SIN", "previsto"].item() == 240.0


def test_receita_escolhida_vai_para_previsto():
    base = {"ridge": 10.0, "gbm": 20.0, "ons": 40.0, "ons_corrigido": 30.0, "ons_ant_corrigido": 50.0, "ons_ant_semana": 60.0}
    pecas = pd.DataFrame([{**base, "peca": "carga"}, {**base, "peca": "solar"}])
    saida = aplicar_receitas(pecas, {"carga": "media_com_ons_corrigido", "solar": "ons_ant_semana"})
    assert saida["previsto"].tolist() == [22.5, 60.0]


def _historico(dias=200, seed=0):
    rng = np.random.default_rng(seed)
    datas = pd.date_range("2026-01-01", periods=dias, freq="D")
    f = pd.DataFrame([(s, d, h) for s in ("SE", "S") for d in datas for h in range(24)], columns=["subsistema", "data", "hora"])
    f["real"] = 1000.0
    f["previsto"] = f["real"] + rng.normal(0, 100, len(f))
    return f


def test_banda_cobre_o_nivel_pedido():
    f = _historico()
    b = banda_walk_forward(f, pd.Timestamp("2026-05-01"))
    dentro = ((b["real"] >= b["banda_inf"]) & (b["real"] <= b["banda_sup"])).mean()
    assert 0.75 < dentro < 0.85
    assert (b["banda_inf"] <= b["previsto"]).all() and (b["previsto"] <= b["banda_sup"]).all()


def test_banda_nao_usa_o_futuro():
    f = _historico()
    ate = pd.Timestamp("2026-05-01")
    q1 = quantis_residuo(f, ate)
    f.loc[f["data"] >= ate - DIA, "previsto"] += 1e6   # estraga a véspera e o futuro
    pd.testing.assert_frame_equal(q1, quantis_residuo(f, ate))


def test_banda_desloca_quando_o_modelo_tem_vies():
    f = _historico()
    f["previsto"] += 300                                # modelo sempre 300 acima
    ate = pd.Timestamp("2026-05-01")
    b = aplicar_banda(f[f["data"] == ate], quantis_residuo(f, ate))
    centro = abs(((b["banda_inf"] + b["banda_sup"]) / 2 - b["real"]).mean())   # viés médio do centro
    assert centro < 30                                  # a banda volta a centrar no real
