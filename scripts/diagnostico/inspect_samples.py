# Entrada: acquisition_validation.json e caminhos de arquivos nele registrados.
# Output: sample_coverage.json. The SQL queries never modify the original data.

"""Read-only coverage inspection of downloaded CSV samples using DuckDB."""
import json
from pathlib import Path
# Importa duckdb: consulta CSV/Parquet usando SQL em processo local.
import duckdb

ROOT = Path(__file__).resolve().parents[2]


def main():
    evidence = json.loads((ROOT / "docs/inventory/acquisition_validation.json").read_text(encoding="utf-8"))
    report = []
    dates = {"balanco-energia-subsistema": "din_instante",
             "ear-diario-por-subsistema": "ear_data",
             "ena-diario-por-subsistema": "ena_data"}
    con = duckdb.connect()
    for item in evidence["checks"]:
        if item["format"] != "CSV" or item["dataset"] not in dates:
            continue
        name = dates[item["dataset"]]
        con.read_csv(item["manifest"]["path"], delimiter=";", sample_size=-1).create_view("sample", replace=True)
        result = con.execute(f'SELECT id_subsistema, count(*), min("{name}"), max("{name}"), count(DISTINCT "{name}") FROM sample GROUP BY 1 ORDER BY 1').fetchall()
        duplicates = con.execute(f'SELECT count(*) FROM (SELECT id_subsistema,"{name}" FROM sample GROUP BY 1,2 HAVING count(*)>1)').fetchone()[0]
        # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
        report.append({"dataset": item["dataset"], "sha256": item["manifest"]["sha256"],
                       "groups_columns": ["id_subsistema", "rows", "min_date", "max_date", "distinct_timestamps"],
                       "groups": result, "duplicate_key_groups": duplicates,
                       "note": "Counts do not establish physical validity or original publication time."})
    (ROOT / "docs/inventory/sample_coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
