"""O INMET mudou o formato de data, hora e cabeçalho ao longo dos anos. Sem rede."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from silver import inmet_frames  # noqa: E402

META = "REGIAO:;SE\nUF:;SP\nESTACAO:;TESTE\nCODIGO (WMO):;A701\nLATITUDE:;-23,5\nLONGITUDE:;-46,6\nALTITUDE:;790\nDATA DE FUNDACAO:;2000-01-01\n"
COLUNAS = "PRECIPITAÇÃO TOTAL, HORÁRIO (mm);TEMPERATURA DO AR - BULBO SECO, HORARIA (°C);\n"
MANIFEST = {"source": "inmet", "dataset": "automatic_stations_annual", "resource_id": "x", "sha256": "abc",
            "ingested_at": "2026-11-10T00:00:00+00:00"}


@pytest.mark.parametrize("cabecalho,linha,esperado", [
    ("DATA (YYYY-MM-DD);HORA (UTC);", "2018-01-02;13:00;0;21,8;\n", datetime(2018, 1, 2, 13, tzinfo=timezone.utc)),
    ("Data;Hora UTC;", "2022/01/02;1300 UTC;0;21,8;\n", datetime(2022, 1, 2, 13, tzinfo=timezone.utc)),
])
def test_formatos_de_data_antigo_e_novo(tmp_path, cabecalho, linha, esperado):
    arquivo = tmp_path / "x.zip"
    with ZipFile(arquivo, "w") as z:
        z.writestr("INMET_SE_SP_A701_TESTE.CSV", (META + cabecalho + COLUNAS + linha).encode("latin-1"))
    _, valid, rejected, _ = next(inmet_frames(arquivo, MANIFEST))
    assert rejected.height == 0
    assert valid["observed_at_utc"][0] == esperado
    assert valid["air_temperature_c"][0] == 21.8
    assert {"data", "hora_utc"} <= set(valid.columns)
