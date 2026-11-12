"""Garantias matemáticas e, principalmente, ausência de vazamento do futuro. Sem rede e sem dados reais."""
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.carga import preparar_subsistema  # noqa: E402
from models.dados import feriados_nacionais  # noqa: E402
from models.ena import preparar_bacia  # noqa: E402
from models.timeseries import ar_coefficient, kalman_regression, ou_half_life  # noqa: E402
from models.validation import annual_folds, block_bootstrap_diff, placebo_shift, skill  # noqa: E402

INDICE = pd.date_range("2018-01-01", "2023-12-31", freq="D")
RNG = np.random.default_rng(1)


def serie_bacia():
    return pd.DataFrame({"ena": 100 + 30 * np.sin(np.arange(len(INDICE)) / 58) + RNG.normal(0, 5, len(INDICE)),
                         "chuva": RNG.gamma(2, 3, len(INDICE))}, index=INDICE)


def serie_carga():
    return pd.DataFrame({"carga": 1000 + RNG.normal(0, 20, len(INDICE)),
                         "programada": 990 + RNG.normal(0, 20, len(INDICE))}, index=INDICE)


def temperatura():
    return pd.DataFrame({"tmed_SP": 22 + RNG.normal(0, 3, len(INDICE))}, index=INDICE)


def test_folds_anuais_cortam_no_ultimo_dia():
    assert annual_folds(2025, "2026-03-10")[-1] == (pd.Timestamp(2026, 1, 1), pd.Timestamp(2026, 3, 11))


def test_ou_recupera_meia_vida_de_ar1_simulado():
    phi, n = 0.9, 50_000
    a = np.zeros(n)
    choques = RNG.normal(0, 1, n)
    for t in range(1, n):
        a[t] = phi * a[t - 1] + choques[t]
    estimado = ar_coefficient(a[:-1], a[1:])
    assert estimado == pytest.approx(phi, abs=0.01)
    assert ou_half_life(estimado) == pytest.approx(np.log(2) / -np.log(phi), rel=0.1)


def test_meia_vida_sem_reversao_e_nan():
    assert np.isnan(ou_half_life(1.02))


def test_kalman_aprende_coeficiente_e_nao_olha_o_futuro():
    n, h = 4000, 3
    x = np.column_stack([np.ones(n), RNG.normal(0, 1, n)])
    y = 0.5 + 2.0 * x[:, 1] + RNG.normal(0, 0.1, n)
    previsto, _ = kalman_regression(x, y, h, r=0.01)
    assert np.mean(np.abs(previsto[-500:] - y[-500:])) < 0.15
    # y[t] é o valor observado em t+h: só pode influenciar previsões a partir de t+h.
    t = 2000
    alterado = y.copy()
    alterado[t:] += 100
    previsto2, _ = kalman_regression(x, alterado, h, r=0.01)
    assert np.array_equal(previsto[:t + h], previsto2[:t + h])
    assert previsto[t + h] != previsto2[t + h]


def test_placebo_preserva_valores_e_desloca():
    s = pd.Series(range(1000), index=pd.date_range("2020-01-01", periods=1000))
    assert placebo_shift(s).iloc[800] == 70


def test_skill_e_bootstrap():
    assert skill(5, 10) == 0.5
    datas = pd.date_range("2020-01-01", periods=400)
    media, baixo, alto = block_bootstrap_diff(datas, np.full(400, 3.0), np.full(400, 1.0))
    assert (media, baixo, alto) == (2.0, 2.0, 2.0)


@pytest.mark.parametrize("h", [1, 7])
def test_ena_memoria_e_chuva_passada_nao_mudam_com_o_futuro(h):
    serie = serie_bacia()
    inicio = pd.Timestamp("2022-01-01")
    corte = pd.Timestamp("2022-06-01")
    original = preparar_bacia(serie, inicio, h)
    alterada = serie.copy()
    alterada.loc[alterada.index > corte, ["ena", "chuva"]] *= 7
    novo = preparar_bacia(alterada, inicio, h)
    colunas = ["a0", "a1", "a2", "a7", "a30", "r1", "r3", "r7", "r15", "r30"]
    pd.testing.assert_frame_equal(original.loc[:corte, colunas], novo.loc[:corte, colunas])


def test_ena_cenario_de_chuva_cobre_exatamente_o_horizonte():
    serie = serie_bacia()
    inicio = pd.Timestamp("2022-01-01")
    x = preparar_bacia(serie, inicio, 7)
    t = pd.Timestamp("2022-03-01")
    janela = serie["chuva"].loc[t + pd.Timedelta(days=1):t + pd.Timedelta(days=7)]
    assert x.loc[t, "futura_total"] == pytest.approx(janela.mean() / serie.loc[serie.index < inicio, "chuva"].mean())


def test_ena_escalas_nao_dependem_do_periodo_de_teste():
    serie = serie_bacia()
    inicio = pd.Timestamp("2022-01-01")
    alterada = serie.copy()
    alterada.loc[alterada.index >= inicio, "ena"] *= 10
    assert preparar_bacia(serie, inicio, 1)["media"].iloc[0] == preparar_bacia(alterada, inicio, 1)["media"].iloc[0]


def test_ena_dia_faltante_nao_contamina_a_climatologia():
    serie = serie_bacia()
    serie.loc["2021-05-10", "ena"] = np.nan
    x = preparar_bacia(serie, pd.Timestamp("2022-01-01"), 1)
    assert x["clima_alvo"].iloc[:-1].notna().all()
    assert np.isnan(x.loc["2021-05-10", "a0"])


def test_carga_variaveis_disponiveis_nao_usam_t_menos_1_nem_t():
    serie, temp = serie_carga(), temperatura()
    t = pd.Timestamp("2023-05-10")
    x, passada, _ = preparar_subsistema(serie, temp)
    alterada, temp2 = serie.copy(), temp.copy()
    # Altera exatamente o que ainda não se sabe na manhã de T−1: a verificada de T−1 e T, e a temperatura.
    alterada.loc[t - pd.Timedelta(days=1):t, "carga"] *= 3
    temp2.loc[t - pd.Timedelta(days=1):t] += 15
    novo, _, _ = preparar_subsistema(alterada, temp2)
    colunas = ["nivel", "r2", "r3", "r7", "r14", "tend", "e2", "e3", "e7", "e14", "e_media7", "e_media28"] + passada
    pd.testing.assert_series_equal(x.loc[t, colunas], novo.loc[t, colunas])


def test_feriados_moveis_e_consciencia_negra():
    assert date(2024, 2, 13) in feriados_nacionais(2024)  # terça de Carnaval
    assert date(2024, 3, 29) in feriados_nacionais(2024)  # Sexta-feira Santa
    assert date(2024, 11, 20) in feriados_nacionais(2024)
    assert date(2022, 11, 20) not in feriados_nacionais(2022)


def test_faixas_horarias_e_estacoes():
    from models.sazonalidade import ESTACOES, faixa_horaria
    assert [faixa_horaria(h) for h in (3, 8, 12, 19, 23)] == ["madrugada_00_05", "manha_06_09", "sol_10_15", "ponta_16_21", "noite_22_23"]
    assert (ESTACOES[1], ESTACOES[7]) == ("verao", "inverno")
