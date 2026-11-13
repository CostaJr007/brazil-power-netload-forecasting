"""D+1: nothing from the target day or the day before may enter the features, except the schedule and the temperature forecast."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.carga_d1 import CAL, ERROS, LAGS, TEMP, TEMP_O, preparar_d1  # noqa: E402

INDICE = pd.date_range("2022-01-01", "2023-12-31 23:00", freq="h")
RNG = np.random.default_rng(3)


def dados():
    n = len(INDICE)
    carga = pd.DataFrame({"carga": 1000 + RNG.normal(0, 20, n), "programada": 990 + RNG.normal(0, 20, n)}, index=INDICE)
    temperatura = pd.DataFrame({"temp_prev": 22 + RNG.normal(0, 3, n), "temp_analise": 22 + RNG.normal(0, 3, n)}, index=INDICE)
    return carga, temperatura


def test_variaveis_nao_usam_carga_de_t_menos_1_nem_de_t():
    carga, temperatura = dados()
    t = pd.Timestamp("2023-05-10")
    original = preparar_d1(carga, temperatura)
    alterada = carga.copy()
    alterada.loc[t - pd.Timedelta(days=1):t + pd.Timedelta(hours=23), "carga"] *= 3
    novo = preparar_d1(alterada, temperatura)
    colunas = ERROS + LAGS + ["nivel", "programada"] + CAL
    pd.testing.assert_frame_equal(original.loc[t, colunas].reset_index(drop=True), novo.loc[t, colunas].reset_index(drop=True))


def test_temperatura_realizada_nao_contamina_variaveis_realizaveis():
    carga, temperatura = dados()
    t = pd.Timestamp("2023-05-10")
    original = preparar_d1(carga, temperatura)
    alterada = temperatura.copy()
    alterada["temp_analise"] += 10
    novo = preparar_d1(carga, alterada)
    pd.testing.assert_frame_equal(original.loc[t, TEMP].reset_index(drop=True), novo.loc[t, TEMP].reset_index(drop=True))
    assert not set(TEMP) & set(TEMP_O)


def test_media_de_temperatura_nao_inclui_o_dia_alvo():
    carga, temperatura = dados()
    t = pd.Timestamp("2023-05-10 14:00")
    alterada = temperatura.copy()
    alterada.loc[t, "temp_prev"] += 10
    a = preparar_d1(carga, temperatura).query("hora == 14").loc["2023-05-10", "t_anom"]
    b = preparar_d1(carga, alterada).query("hora == 14").loc["2023-05-10", "t_anom"]
    assert b - a == 10 or abs(b - a - 10) < 1e-9


def test_uma_linha_por_hora_e_dia():
    carga, temperatura = dados()
    x = preparar_d1(carga, temperatura)
    assert len(x) == len(INDICE)
    assert x.reset_index().duplicated(["data", "hora"]).sum() == 0
