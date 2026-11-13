"""PLD estimado: CMO limitado ao piso e aos tetos da ANEEL. Sem rede e sem dados reais."""
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gold  # noqa: E402


def pld_views():
    code = "\n".join(line for line in gold.VIEWS.splitlines() if not line.strip().startswith("--"))
    return [s.strip() for s in code.split(";") if "vw_pld_estimado" in s.split("AS", 1)[0]]


@pytest.fixture
def con():
    """In 2024: floor 61.07; hourly cap 1,470.57; structural cap 716.80."""
    connection = duckdb.connect()
    connection.execute("""
        CREATE TABLE silver_cmo_semi_horario AS
        SELECT * FROM (VALUES
            ('SE', TIMESTAMP '2024-03-01 00:00:00', 10.0, false),
            ('SE', TIMESTAMP '2024-03-01 00:30:00', 20.0, false),
            ('SE', TIMESTAMP '2024-03-01 01:00:00', 200.0, false),
            ('SE', TIMESTAMP '2024-03-01 01:30:00', 300.0, false),
            ('N',  TIMESTAMP '2024-03-02 00:00:00', 5000.0, false),
            ('N',  TIMESTAMP '2024-03-02 00:30:00', 5000.0, false),
            ('SIN', TIMESTAMP '2024-03-01 00:00:00', 100.0, true),
            ('SE', TIMESTAMP '2020-06-01 00:00:00', 100.0, false)
        ) AS t(id_subsistema, _event_time_source, val_cmo, _is_sin_aggregate)""")
    gold.create_pld_limits(connection)
    for statement in pld_views():
        connection.execute(statement)
    return connection


def test_horario_aplica_piso_teto_e_media_das_meias_horas(con):
    rows = con.execute("""SELECT subsistema, cmo_medio, pld_estimado, origem, meias_horas
                          FROM vw_pld_estimado_horario ORDER BY hora, subsistema""").fetchall()
    assert rows == [("SE", 15.0, 61.07, "piso", 2),
                    ("SE", 250.0, 250.0, "cmo", 2),
                    ("N", 5000.0, 1470.57, "teto_horario", 2)]


def test_diario_limita_ao_teto_estrutural(con):
    rows = dict(con.execute("""SELECT subsistema, (pld_estimado, teto_estrutural_aplicado)
                               FROM vw_pld_estimado_diario""").fetchall())
    assert rows["N"] == (716.80, True)
    assert rows["SE"] == (pytest.approx((61.07 + 250.0) / 2), False)


def test_limites_cobrem_todos_os_anos_do_pld_horario(con):
    years = [r[0] for r in con.execute("SELECT ano FROM pld_limites ORDER BY ano").fetchall()]
    assert years == list(range(2021, 2027))
    assert con.execute("SELECT count(*) FROM pld_limites WHERE NOT pld_min < pld_max_estrutural "
                       "OR NOT pld_max_estrutural < pld_max_horario").fetchone()[0] == 0
