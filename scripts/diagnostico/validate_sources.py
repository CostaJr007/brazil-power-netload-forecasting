# Input: local catalog and the URLs recorded in it. Output: Bronze and acquisition_validation.json.
# This routine uses the network, has a limited selection and does not download the full ONS history.

"""Small live smoke check; downloads only a bounded set, never full history."""
import json
from pathlib import Path
from zipfile import ZipFile

# Scripts in this subfolder reuse the modules in scripts/ (acquire, pipeline...).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from acquire import DATA_DIR, Store, atomic_json, profile_csv, resource_plan, utcnow

ROOT = Path(__file__).resolve().parents[2]


def main():
    catalog = json.loads((DATA_DIR / "catalog/latest.json").read_text(encoding="utf-8"))
    store = Store(DATA_DIR)
    evidence = {"checked_at": utcnow(), "checks": [], "errors": []}
    checks = [("balanco-energia-subsistema", "CSV", "2025", False),
              ("balanco-energia-subsistema", "PARQUET", "2025", False),
              ("ear-diario-por-subsistema", "CSV", "2025", False),
              ("ena-diario-por-subsistema", "CSV", "2025", False),
              ("bacia_contorno", "ZIP", "", False),
              ("programacao_diaria", "JSON", "", True),
              ("carga-energia-programada", "JSON", "", True),
              ("carga-energia-verificada", "JSON", "", True)]
    try:
        for dataset, fmt, contains, docs in checks:
            try:
                plan = resource_plan(catalog, [dataset], fmt, contains, docs)
                if not plan:
                    raise ValueError("No catalogue resource found")
                item = plan[0]
                meta = store.fetch("ons", dataset, item["resource_id"], item["url"], context=item)
                entry = {"dataset": dataset, "format": fmt, "manifest": meta}
                if fmt == "CSV":
                    entry["profile"] = profile_csv(meta["path"], [])
                elif fmt == "ZIP":
                    with ZipFile(meta["path"]) as archive:
                        entry["zip_members"] = archive.namelist()
                        entry["corrupt_member"] = archive.testzip()
                elif fmt == "JSON":
                    value = json.loads(Path(meta["path"]).read_text(encoding="utf-8-sig"))
                    entry["json_type"] = type(value).__name__
                # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
                evidence["checks"].append(entry)
                print(f"OK {dataset} {fmt}", flush=True)
            except Exception as exc:
                # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
                evidence["errors"].append({"dataset": dataset, "format": fmt, "error": str(exc)})
                print(f"ERROR {dataset} {fmt}: {exc}", flush=True)
            atomic_json(ROOT / "docs/inventory/acquisition_validation.json", evidence)
    finally:
        store.close()
    return int(bool(evidence["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
