"""Generate initial contracts from the schemas observed in the ONS audit.

Does not download data. Review configs/ons_contracts.json when a source changes its schema.
"""
import json
# Scripts in this subfolder reuse the modules in scripts/ (acquire, pipeline...).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from acquire import ROOT, atomic_json


def main():
    audit = json.loads((ROOT / "docs/inventory/endpoints_audit.json").read_text(encoding="utf-8"))
    contracts = {}
    for item in audit["results"]:
        columns = item.get("content", {}).get("columns", [])
        if not columns:
            continue
        names = [c["name"] for c in columns]
        # Numeric types or val_ fields are typed; dates stay out of this list.
        numeric = [c["name"] for c in columns if c["type"] in {"DOUBLE", "FLOAT", "BIGINT", "INTEGER"}
                   or c["name"].startswith("val_")
                   or (c["name"].startswith(("ear_", "ena_")) and c["name"] not in {"ear_data", "ena_data"})]
        event = item.get("content", {}).get("reference_column")
        # val_tipoperda is a category (e.g. percentage/metres), despite the val_ prefix.
        numeric = [n for n in numeric if n != "val_tipoperda" and not n.startswith(("id_", "cod_"))]
        contracts[item["dataset"]] = {"required": names, "numeric": numeric,
                                      "event_column": event, "timezone": "not_verified",
                                      "origin": "observed_schema_initial_contract"}
    atomic_json(ROOT / "configs/ons_contracts.json", contracts)
    print(f"Contratos locais: {len(contracts)}")


if __name__ == "__main__":
    main()
