"""Balance cleaning before ML: impossible or frozen values become missing, the rest stays intact."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.dados import tratar_balanco  # noqa: E402

INSTANTES = pd.date_range("2024-11-10", periods=48, freq="h")
RNG = np.random.default_rng(3)


def balanco():
    hora = INSTANTES.hour
    sol = np.where((hora >= 6) & (hora <= 18), 1000 * np.sin(np.pi * (hora - 6) / 12), 0.0)
    return pd.DataFrame({"subsistema": "SE", "instante": INSTANTES, "carga": 40000 + RNG.normal(0, 500, 48),
                         "eolica": 30 + RNG.normal(0, 5, 48).clip(-20), "solar": sol + RNG.normal(0, 1, 48).clip(0)})


def test_dados_limpos_nao_mudam():
    original = balanco()
    pd.testing.assert_frame_equal(tratar_balanco(original), original)


def test_solar_noturna_vira_ausente_e_nao_zero():
    frame = balanco()
    frame.loc[frame["instante"].dt.hour == 2, "solar"] = 900.0
    tratado = tratar_balanco(frame)
    assert tratado.loc[tratado["instante"].dt.hour == 2, "solar"].isna().all()
    assert tratado["solar"].isna().sum() == 2


def test_valor_congelado_vira_ausente():
    frame = balanco()
    frame.loc[10:14, "eolica"] = 2876.0
    tratado = tratar_balanco(frame)
    assert tratado.loc[10:14, "eolica"].isna().all()
    assert tratado["eolica"].notna().sum() == 48 - 5


def test_zero_repetido_nao_e_congelado_e_carga_zero_e_ausente():
    frame = balanco()
    frame.loc[5, "carga"] = 0.0
    tratado = tratar_balanco(frame)
    assert np.isnan(tratado.loc[5, "carga"])
    assert (tratado.loc[tratado["instante"].dt.hour == 23, "solar"] >= 0).all()  # noite em zero continua zero
