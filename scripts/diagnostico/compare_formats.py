# Input: paths of the two files on the command line. Output: result on screen and optional JSON.
# Does not download files: equivalence holds under the types and conversions DuckDB applies.

"""Optional DuckDB check: compare logical CSV/Parquet records, retaining duplicates.

Pass --decimal , if the SOURCE dictionary specifies comma decimals.
This is not an API-versus-CSV equivalence claim.
"""
import argparse
import json
from pathlib import Path


def main():
    import duckdb

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv")
    parser.add_argument("parquet")
    parser.add_argument("--decimal", default=".", choices=[".", ","])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    con = duckdb.connect()
    con.read_csv(args.csv, delimiter=";", decimal=args.decimal, sample_size=-1).create_view("csv_data")
    con.read_parquet(args.parquet).create_view("parquet_data")
    csv_cols = [r[0] for r in con.execute("DESCRIBE csv_data").fetchall()]
    pq_cols = [r[0] for r in con.execute("DESCRIBE parquet_data").fetchall()]
    if set(csv_cols) != set(pq_cols):
        raise ValueError(f"Different columns: CSV={csv_cols}, Parquet={pq_cols}")
    cols = ",".join('"' + c.replace('"', '""') + '"' for c in csv_cols)
    # DuckDB chooses compatible types; inspect inferred schemas before interpreting.
    delta_a = con.execute(f"SELECT count(*) FROM ((SELECT {cols} FROM csv_data) EXCEPT ALL (SELECT {cols} FROM parquet_data))").fetchone()[0]
    delta_b = con.execute(f"SELECT count(*) FROM ((SELECT {cols} FROM parquet_data) EXCEPT ALL (SELECT {cols} FROM csv_data))").fetchone()[0]
    result = {"csv_only_rows": delta_a, "parquet_only_rows": delta_b,
                      "equal_under_duckdb_type_coercion": delta_a == delta_b == 0,
                      "csv_schema": con.execute("DESCRIBE csv_data").fetchall(),
                      "parquet_schema": con.execute("DESCRIBE parquet_data").fetchall()}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, default=str))
    return int(bool(delta_a or delta_b))


if __name__ == "__main__":
    raise SystemExit(main())
