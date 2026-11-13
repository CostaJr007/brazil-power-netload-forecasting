"""Join every source into a single table: one row per subsystem × hour.

Output: data/gold/tabela_modelo.parquet and .csv (dictionary in docs/tabela_modelo.md).
Columns hold the value of the instant itself, WITHOUT lag: anyone training a model must
apply the lag given in the dictionary, or they will use information that did not exist yet.

Run: .\\.venv\\Scripts\\python.exe scripts/tabela_modelo.py
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from acquire import DATA_DIR  # noqa: E402
from models.carga import calendario  # noqa: E402
from models.dados import carregar_carga_horaria, carregar_extras, carregar_previstas_extras, carregar_temperatura_prevista, conectar  # noqa: E402

COLUNAS_PREVISTAS = ["radiacao_prev", "vento_prev", "umidade_prev", "nuvens_prev"]
COLUNAS_CALENDARIO = ["dia_semana", "mes", "feriado", "vespera", "pos_feriado", "ponte"]


def montar_tabela(carga, extras, temperatura, previstas=None):
    """Always left joins onto load: each subsystem × hour stays exactly one row."""
    tabela = carga.copy()
    tabela["data"] = tabela["instante"].dt.normalize()
    tabela["hora"] = tabela["instante"].dt.hour
    temp = temperatura.groupby(["subsistema", "instante"], as_index=False)[["temp_prev_48h", "temp_analise"]].mean()
    tabela = tabela.merge(temp, on=["subsistema", "instante"], how="left", validate="one_to_one")
    if previstas is not None:
        media = previstas.groupby(["subsistema", "instante"], as_index=False)[COLUNAS_PREVISTAS].mean()
        tabela = tabela.merge(media, on=["subsistema", "instante"], how="left", validate="one_to_one")
    diarias = pd.concat([d.rename_axis("data").reset_index().assign(subsistema=s) for s, d in extras.items()], ignore_index=True)
    tabela = tabela.merge(diarias, on=["subsistema", "data"], how="left", validate="many_to_one")
    cal = calendario(pd.DatetimeIndex(tabela["data"].unique()))[COLUNAS_CALENDARIO].rename_axis("data").reset_index()
    return tabela.merge(cal, on="data", how="left", validate="many_to_one").sort_values(["subsistema", "instante"]).reset_index(drop=True)


def main():
    con = conectar()
    carga = carregar_carga_horaria(con)
    extras = carregar_extras(con)
    con.close()
    arquivo_previstas = DATA_DIR / "gold/previsao_vento_sol.parquet"
    previstas = carregar_previstas_extras() if arquivo_previstas.exists() else None
    tabela = montar_tabela(carga, extras, carregar_temperatura_prevista(), previstas)
    destino = DATA_DIR / "gold/tabela_modelo"
    tabela.to_parquet(destino.with_suffix(".parquet"), index=False)
    tabela.to_csv(destino.with_suffix(".csv"), index=False)
    print(f"{len(tabela):,} linhas, {tabela.shape[1]} colunas, de {tabela['instante'].min()} a {tabela['instante'].max()}")
    print("Preenchimento (%):")
    print((tabela.notna().mean() * 100).round(1).to_string())


if __name__ == "__main__":
    main()
