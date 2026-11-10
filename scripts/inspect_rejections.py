"""Mostra as rejeições mais recentes por conjunto, sem modificar dados."""
import json
from pathlib import Path
import polars as pl
from acquire import DATA_DIR, ROOT


def main():
    latest = {}
    for path in (DATA_DIR / "silver/ons").rglob("snapshot.json"):
        report = json.loads(path.read_text(encoding="utf-8"))
        name = report["source_manifest"]["dataset"]
        if report["status"] != "published" and (name not in latest or path.stat().st_mtime > latest[name][0]):
            latest[name] = (path.stat().st_mtime, report)
    for name, (_, report) in latest.items():
        paths = [p for p in report["files"] if p.endswith(".quarantine.parquet")]
        frame = pl.read_parquet(paths)
        print(name, frame.height)
        print(json.dumps(frame.select("_quality_errors").explode("_quality_errors", empty_as_null=True).group_by("_quality_errors").len().to_dicts()))
        cols = [c for c in frame.columns if "percentual" in c or c.startswith("din_")]
        print(json.dumps(frame.select(cols + ["_quality_errors"]).head(5).to_dicts(), default=str))


if __name__ == "__main__":
    main()
