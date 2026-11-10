"""Gera contratos iniciais a partir dos schemas observados na auditoria ONS.

Não baixa dados. Revise configs/ons_contracts.json quando a fonte mudar o schema.
"""
import json
# Scripts desta subpasta reutilizam os módulos de scripts/ (acquire, pipeline...).
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
        # Tipos numéricos ou campos val_ são tratados; datas ficam fora dessa lista.
        numeric = [c["name"] for c in columns if c["type"] in {"DOUBLE", "FLOAT", "BIGINT", "INTEGER"}
                   or c["name"].startswith("val_")
                   or (c["name"].startswith(("ear_", "ena_")) and c["name"] not in {"ear_data", "ena_data"})]
        event = item.get("content", {}).get("reference_column")
        # val_tipoperda é uma categoria (ex.: porcentagem/metros), apesar do prefixo val_.
        numeric = [n for n in numeric if n != "val_tipoperda" and not n.startswith(("id_", "cod_"))]
        contracts[item["dataset"]] = {"required": names, "numeric": numeric,
                                      "event_column": event, "timezone": "not_verified",
                                      "origin": "observed_schema_initial_contract"}
    atomic_json(ROOT / "configs/ons_contracts.json", contracts)
    print(f"Contratos locais: {len(contracts)}")


if __name__ == "__main__":
    main()
