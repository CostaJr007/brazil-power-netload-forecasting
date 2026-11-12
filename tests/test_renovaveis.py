"""Peças da carga líquida: previsão só com o que existe na noite de T−1."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.carga_d1 import LAGS, TEMP, preparar_d1  # noqa: E402
from models.renovaveis import corrigir_vies, corrigir_vies_semana, folds_trimestrais, preparar_fonte, referencias_ons  # noqa: E402

INDICE = pd.date_range("2024-02-01", "2025-06-30 23:00", freq="h")
RNG = np.random.default_rng(9)


def dados():
    serie = pd.Series(100 + RNG.normal(0, 10, len(INDICE)), index=INDICE)
    previsoes = pd.DataFrame({"vento": 8 + RNG.normal(0, 2, len(INDICE))}, index=INDICE)
    return serie, previsoes


def test_folds_trimestrais_sem_buraco_nem_sobreposicao():
    folds = folds_trimestrais(2025, "2025-08-15")
    assert folds[0] == (pd.Timestamp(2025, 1, 1), pd.Timestamp(2025, 4, 1))
    assert folds[1][0] == folds[0][1]
    assert folds[-1][1] == pd.Timestamp(2025, 8, 16)


def test_variaveis_nao_usam_geracao_de_t_menos_1_nem_de_t():
    serie, previsoes = dados()
    t = pd.Timestamp("2025-03-10")
    alterada = serie.copy()
    alterada.loc[t - pd.Timedelta(days=1):t + pd.Timedelta(hours=23)] *= 4
    colunas = ["nivel", "r2", "r7", "tend", "persistencia", "media7", "vento", "vento_a", "vento_a2"]
    a = preparar_fonte(serie, previsoes).loc[t, colunas].reset_index(drop=True)
    b = preparar_fonte(alterada, previsoes).loc[t, colunas].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_anomalia_da_previsao_nao_inclui_o_proprio_dia():
    serie, previsoes = dados()
    t = pd.Timestamp("2025-03-10 14:00")
    alterada = previsoes.copy()
    alterada.loc[t, "vento"] += 5
    a = preparar_fonte(serie, previsoes).query("hora == 14").loc["2025-03-10", "vento_a"]
    b = preparar_fonte(serie, alterada).query("hora == 14").loc["2025-03-10", "vento_a"]
    assert abs(b - a - 5) < 1e-9


def test_d_mais_2_nao_usa_geracao_de_t_menos_2():
    serie, previsoes = dados()
    t = pd.Timestamp("2025-03-10")
    alterada = serie.copy()
    alterada.loc[t - pd.Timedelta(days=2):t + pd.Timedelta(hours=23)] *= 4
    colunas = ["nivel", "r2", "r7", "tend", "persistencia", "media7"]
    a = preparar_fonte(serie, previsoes, gap=3).loc[t, colunas].reset_index(drop=True)
    b = preparar_fonte(alterada, previsoes, gap=3).loc[t, colunas].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_carga_d_mais_2_nao_usa_carga_de_t_menos_2():
    carga = pd.DataFrame({"carga": 1000 + RNG.normal(0, 50, len(INDICE)), "programada": np.nan}, index=INDICE)
    temperatura = pd.DataFrame({"temp_prev": 25 + RNG.normal(0, 3, len(INDICE)), "temp_analise": 25.0}, index=INDICE)
    t = pd.Timestamp("2025-03-10")
    alterada = carga.copy()
    alterada.loc[t - pd.Timedelta(days=2):t + pd.Timedelta(hours=23), "carga"] *= 3
    colunas = LAGS + TEMP
    a = preparar_d1(carga, temperatura, gap=3).loc[t, colunas].reset_index(drop=True)
    b = preparar_d1(alterada, temperatura, gap=3).loc[t, colunas].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_ons_ant_em_d_mais_2_e_a_programacao_de_t_menos_1():
    instantes = pd.date_range("2025-06-01", periods=72, freq="h")
    d = pd.DataFrame({"eolica": np.arange(72.0)}, index=pd.Index(instantes, name="instante"))
    ref = referencias_ons(d, "eolica", horizonte=2).set_index(["data", "hora"])
    linha = ref.loc[(pd.Timestamp("2025-06-03"), 5)]
    assert linha["ons"] == 53.0 and linha["ons_ant"] == 29.0  # 03/06 05h e 02/06 05h
    assert ref.loc[(pd.Timestamp("2025-06-01"), 5), "ons_ant"] != ref.loc[(pd.Timestamp("2025-06-01"), 5), "ons_ant"]  # NaN: não há véspera


def test_vies_por_dia_da_semana_remove_efeito_de_segunda_sem_usar_o_proprio_dia():
    datas = pd.date_range("2025-01-06", periods=70, freq="D")  # começa numa segunda
    real = np.where(datas.day_of_week == 0, 80.0, 100.0)
    g = pd.DataFrame({"data": datas, "hora": 12, "ons_ant": 100.0, "real": real})
    corrigido = corrigir_vies_semana(g, gap=3)
    segunda = g.index[(datas.day_of_week == 0)][-1]
    assert abs(corrigido.loc[segunda] - 80.0) < 1e-9  # aprendeu que segunda fica 20 abaixo
    alterado = g.copy()
    alterado.loc[segunda - 2:segunda, "real"] = 0.0  # T−2, T−1 e T não podem mudar a correção de T
    assert abs(corrigir_vies_semana(alterado, gap=3).loc[segunda] - corrigido.loc[segunda]) < 1e-9


def test_correcao_de_vies_usa_so_erros_ate_t_menos_2():
    datas = pd.date_range("2025-01-01", periods=60, freq="D")
    g = pd.DataFrame({"data": datas, "hora": 12, "ons": 110.0, "real": 100.0})
    corrigido = corrigir_vies(g)
    assert abs(corrigido.iloc[40] - 100.0) < 1e-9  # viés constante de +10 removido
    alterado = g.copy()
    alterado.loc[39:40, "real"] = 0.0  # erros de T−1 e de T não podem mudar a correção de T
    assert abs(corrigir_vies(alterado).iloc[40] - corrigido.iloc[40]) < 1e-9


def test_nivel_zero_nao_gera_alvo():
    serie, previsoes = dados()
    x = preparar_fonte(serie * 0, previsoes)
    assert x["alvo"].notna().sum() == 0
