# Input: data/catalog/latest.json and configs/ons.json. Output: docs/inventory.
# No network and no changes to the energy files.

"""Export audited catalogue metadata without claiming actual temporal coverage."""
import csv
import json
from pathlib import Path

# ROOT (project root) and DATA_DIR (configurable data folder) come from the acquisition core.
# Scripts in this subfolder reuse the modules in scripts/ (acquire, pipeline...).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from acquire import DATA_DIR, ROOT


def main():
    catalog = json.loads((DATA_DIR / "catalog/latest.json").read_text(encoding="utf-8"))
    selected = set(json.loads((ROOT / "configs/ons.json").read_text(encoding="utf-8"))["selected"])
    out = ROOT / "docs/inventory"
    out.mkdir(parents=True, exist_ok=True)
    columns = ["dataset", "resource_id", "name", "format", "url", "created",
               "last_modified", "metadata_modified", "size"]
    with (out / "ons_resources.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for package in catalog["packages"]:
            for resource in package.get("resources", []):
                # Escreve um registro CSV, associando os valores aos nomes de colunas configurados.
                writer.writerow({"dataset": package["name"], **{k: resource.get(k) for k in columns if k != "dataset"}})
    lines = ["# ONS inventory — metadata collected from the API", "",
             f"Collected UTC: {catalog['discovered_at']}. Datasets resolved: {len(catalog['packages'])}.", "",
             "Resource dates below are catalog metadata; they do not prove record coverage or historical publication.", "",
             "Samples actually downloaded are recorded in acquisition_validation.json. No quality indicator was inferred from the source's reputation.", ""]
    for p in catalog["packages"]:
        formats = sorted({str(r.get("format", "")) for r in p.get("resources", [])})
        lines.extend([f"## {p['title']}", "", f"- Slug: `{p['name']}`; initial selection: {'yes' if p['name'] in selected else 'no'}.",
                      f"- Source: https://dados.ons.org.br/dataset/{p['name']}",
                      f"- Recursos: {len(p.get('resources', []))}; formatos: {', '.join(formats)}.",
                      f"- Declared licence: {p.get('license_title', p.get('license_id'))}.",
                      "", str(p.get("notes", "")), ""])
    (out / "ons_catalog.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"datasets": len(catalog["packages"]),
                      "resources": sum(len(p.get("resources", [])) for p in catalog["packages"]),
                      "selected": len(selected), "output": str(out)}))


if __name__ == "__main__":
    main()
