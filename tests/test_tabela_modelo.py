"""A tabela única não pode duplicar nem perder linhas ao juntar as fontes."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tabela_modelo import montar_tabela  # noqa: E402

INSTANTES = pd.date_range("2024-03-01", periods=48, freq="h")


def test_uma_linha_por_subsistema_e_hora_e_media_das_cidades():
    carga = pd.concat([pd.DataFrame({"subsistema": s, "instante": INSTANTES, "carga": 100.0, "programada": 95.0}) for s in ("S", "N")])
    temperatura = pd.concat([pd.DataFrame({"subsistema": "S", "cidade": c, "instante": INSTANTES, "temp_prev_48h": t, "temp_analise": t})
                             for c, t in (("a", 20.0), ("b", 30.0))])
    diarias = pd.DataFrame({"ear": [50.0, 51.0]}, index=pd.to_datetime(["2024-03-01", "2024-03-02"]))
    tabela = montar_tabela(carga, {"S": diarias, "N": diarias}, temperatura)
    assert len(tabela) == 96
    assert not tabela.duplicated(["subsistema", "instante"]).any()
    sul = tabela[tabela["subsistema"] == "S"]
    assert (sul["temp_prev_48h"] == 25.0).all()
    assert sul.loc[sul["instante"] == pd.Timestamp("2024-03-02 05:00"), "ear"].item() == 51.0
    assert tabela[tabela["subsistema"] == "N"]["temp_prev_48h"].isna().all()
