"""Views de acompanhamento: somas sem dupla contagem e percentuais ponderados. Sem dados reais."""
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gold  # noqa: E402

NOMES = ("vw_ena_bacia_diaria", "vw_ena_bacia_sem_dupla_contagem", "vw_hidro_subsistema_diaria", "vw_conferencia_soma_bacias",
         "vw_balanco_horario_sin", "vw_cortes_renovaveis_diario")


def criar_views(con):
    code = "\n".join(line for line in gold.VIEWS.splitlines() if not line.strip().startswith("--"))
    for statement in (s.strip() for s in code.split(";") if s.strip()):
        if statement.split()[2] in NOMES:
            con.execute(statement)


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("""CREATE TABLE silver_ena_diario_por_bacia AS SELECT * FROM (VALUES
        ('AMAZONAS', TIMESTAMP '2025-01-01', 100.0, 90.0, 80.0), ('PARANA', TIMESTAMP '2025-01-01', 50.0, 90.0, 40.0),
        ('AMAZONAS', TIMESTAMP '2026-01-01', 100.0, 90.0, 80.0), ('MADEIRA', TIMESTAMP '2026-01-01', 60.0, 90.0, 50.0),
        ('XINGU', TIMESTAMP '2026-01-01', 40.0, 90.0, 30.0), ('PARANA', TIMESTAMP '2026-01-01', 50.0, 90.0, 40.0)
        ) AS t(nom_bacia, _event_time_source, ena_bruta_bacia_mwmed, ena_bruta_bacia_percentualmlt, ena_armazenavel_bacia_mwmed)""")
    c.execute("""CREATE TABLE silver_ena_diario_por_subsistema AS SELECT * FROM (VALUES
        ('SE', TIMESTAMP '2026-01-01', 90.0, 90.0, 70.0), ('N', TIMESTAMP '2026-01-01', 60.0, 60.0, 50.0),
        ('SE', TIMESTAMP '2025-01-01', 100.0, 100.0, 70.0), ('N', TIMESTAMP '2025-01-01', 50.0, 50.0, 50.0)
        ) AS t(id_subsistema, _event_time_source, ena_bruta_regiao_mwmed, ena_bruta_regiao_percentualmlt, ena_armazenavel_regiao_mwmed)""")
    c.execute("""CREATE TABLE silver_ear_diario_por_subsistema AS SELECT * FROM (VALUES
        ('SE', TIMESTAMP '2026-01-01', 300.0, 1000.0, 30.0), ('N', TIMESTAMP '2026-01-01', 90.0, 100.0, 90.0)
        ) AS t(id_subsistema, _event_time_source, ear_verif_subsistema_mwmes, ear_max_subsistema, ear_verif_subsistema_percentual)""")
    c.execute("""CREATE TABLE silver_restricao_coff_fotovoltaica AS SELECT * FROM (VALUES
        ('NE', TIMESTAMP '2026-01-01 12:00', 'ENE', 60.0, 40.0), ('NE', TIMESTAMP '2026-01-01 12:30', NULL, 100.0, NULL)
        ) AS t(id_subsistema, _event_time_source, cod_razaorestricao, val_geracao, val_geracaonaorealizadaapurada)""")
    c.execute("CREATE TABLE silver_restricao_coff_eolica_usi AS SELECT * FROM silver_restricao_coff_fotovoltaica LIMIT 0")
    c.execute("""CREATE TABLE vw_balanco_carga_liquida AS SELECT * FROM (VALUES
        ('SE', TIMESTAMP '2026-01-01 12:00', 10.0, 1.0, 2.0, 5.0, 2.0, 7.0), ('S', TIMESTAMP '2026-01-01 12:00', 10.0, 1.0, 2.0, 5.0, 2.0, 7.0),
        ('NE', TIMESTAMP '2026-01-01 12:00', 10.0, 1.0, 2.0, 5.0, 2.0, 7.0), ('N', TIMESTAMP '2026-01-01 12:00', 10.0, 1.0, 2.0, 5.0, 2.0, 7.0),
        ('SE', TIMESTAMP '2026-01-01 13:00', 10.0, 1.0, 2.0, 5.0, 2.0, 7.0)
        ) AS t(subsistema, instante_fonte, carga_mwmed, eolica_mwmed, solar_mwmed, hidraulica_mwmed, termica_mwmed, carga_liquida_mwmed)""")
    criar_views(c)
    return c


def test_amazonas_sai_so_quando_ha_sub_bacias(con):
    linhas = dict(con.execute("SELECT data_referencia::VARCHAR, sum(ena_bruta_mwmed) FROM vw_ena_bacia_sem_dupla_contagem GROUP BY 1").fetchall())
    assert linhas == {"2025-01-01": 150.0, "2026-01-01": 150.0}


def test_conferencia_fecha_com_sin(con):
    assert con.execute("SELECT diferenca_mwmed FROM vw_conferencia_soma_bacias WHERE data_referencia = '2026-01-01'").fetchone()[0] == 0


def test_percentuais_do_sin_sao_ponderados(con):
    ena, pct_mlt, ear_pct = con.execute("SELECT ena_mwmed, ena_pct_mlt, ear_pct FROM vw_hidro_subsistema_diaria WHERE subsistema = 'SIN' AND data_referencia = '2026-01-01'").fetchone()
    assert ena == 150.0
    # MLT implícita: 90/0,9 + 60/0,6 = 200 MWmed; 150/200 = 75%.
    assert pct_mlt == pytest.approx(75.0)
    # (300 + 90) / (1000 + 100), e não a média simples de 30% e 90%.
    assert ear_pct == pytest.approx(100 * 390 / 1100)


def test_cortes_em_mw_medio_e_percentual_do_potencial(con):
    g, corte, pct = con.execute("SELECT geracao_mwmed, corte_mwmed, corte_pct_do_potencial FROM vw_cortes_renovaveis_diario").fetchone()
    assert (g, corte) == (80.0, 20.0)
    assert pct == pytest.approx(40 / 200)


def test_sin_horario_exige_os_quatro_subsistemas(con):
    assert con.execute("SELECT count(*), max(carga_mwmed) FROM vw_balanco_horario_sin").fetchone() == (1, 40.0)


def test_horarios_ignoram_downloads_repetidos_e_usam_hora_local():
    import pandas as pd

    from horarios_publicacao import resumir
    manifestos = pd.DataFrame({"conjunto": ["a", "a", "a"], "recurso": ["r", "r", "r"], "sha256": ["x", "x", "y"],
                               "ultima_modificacao": ["Tue, 10 Nov 2026 22:00:00 GMT", "Tue, 10 Nov 2026 22:00:00 GMT", "Wed, 11 Nov 2026 10:00:00 GMT"]})
    resultado = resumir(manifestos)["a"]
    assert resultado["revisoes"] == 2
    assert resultado["revisoes_por_hora_local"] == {7: 1, 19: 1}
    assert resultado["dias_observados"] == 2
