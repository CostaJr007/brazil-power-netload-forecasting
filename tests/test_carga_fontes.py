"""Reservatórios, geração e clima observado só podem entrar com defasagem de 2 dias."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.carga_fontes import COLUNAS_CLIMA, COLUNAS_GERACAO, adicionar_programada, variaveis_diarias  # noqa: E402

DATAS = pd.date_range("2022-01-01", "2023-12-31", freq="D")
RNG = np.random.default_rng(5)


def extras():
    colunas = COLUNAS_CLIMA + COLUNAS_GERACAO + ["ear", "ena_pct"]
    return pd.DataFrame(RNG.uniform(10, 100, (len(DATAS), len(colunas))), index=DATAS, columns=colunas)


def test_extras_nao_usam_t_menos_1_nem_t():
    base, t = extras(), pd.Timestamp("2023-05-10")
    alterado = base.copy()
    alterado.loc[t - pd.Timedelta(days=1):] *= 5
    pd.testing.assert_series_equal(variaveis_diarias(base).loc[t], variaveis_diarias(alterado).loc[t])


def test_extras_mudam_com_t_menos_2():
    base, t = extras(), pd.Timestamp("2023-05-10")
    alterado = base.copy()
    alterado.loc[t - pd.Timedelta(days=2), "ear"] += 7
    assert variaveis_diarias(alterado).loc[t, "ear"] == base.loc[t - pd.Timedelta(days=2), "ear"] + 7


def test_programada_de_t_nao_entra_nas_variaveis_para_preve_la():
    t = pd.Timestamp("2023-05-10")
    x = pd.DataFrame({"hora": 10, "programada": RNG.uniform(900, 1100, len(DATAS))}, index=DATAS)
    alterado = x.copy()
    alterado.loc[t, "programada"] *= 2
    colunas = ["nivel_p", "p1", "p7", "p14", "tend_p"]
    pd.testing.assert_series_equal(adicionar_programada(x).loc[t, colunas], adicionar_programada(alterado).loc[t, colunas])
