# Input: endpoints_audit.json, load_api_probe.json and the local audit files.
# Output: updates the audit JSON and Markdown. Makes no new HTTP requests.

"""Finalize observed endpoint evidence without inferring cadastral freshness."""
import json
from pathlib import Path
import duckdb

# Scripts in this subfolder reuse the modules in scripts/ (acquire, pipeline...).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from acquire import ROOT, atomic_json, resolve_data_path


def main():
    path = ROOT / "docs/inventory/endpoints_audit.json"
    audit = json.loads(path.read_text(encoding="utf-8"))
    probes = json.loads((ROOT / "docs/inventory/load_api_probe.json").read_text(encoding="utf-8"))
    cadastral = {"reservatorio", "capacidade-geracao", "usina_conjunto", "usina_pqu", "res_cotaareavolume", "bacia_contorno"}
    con = duckdb.connect()
    for item in audit["results"]:
        content = item.get("content", {})
        if item["dataset"] in cadastral:
            content["reference_column"] = None
            content["max_reference"] = None
            item["freshness_assessment"] = "registry: HTTP confirmed; content freshness not proven by event dates"
        if item["dataset"] in {"carga-energia-verificada", "carga-energia-programada"}:
            kind = item["dataset"].split("-")[-1]
            item["api_probe"] = next(p for p in probes if p["kind"] == kind)
            item["status"] = "http_200_empty_response_without_area"
        if item["dataset"] in {"programacao_x_previsao", "grandezas_fluviometricas"}:
            con.read_parquet(str(resolve_data_path(content["path"]))).create_view("sample", replace=True)
            names = [r[0] for r in con.execute("DESCRIBE sample").fetchall() if r[0].startswith(("dat_", "din_"))]
            for name in names:
                escaped = '"' + name.replace('"', '""') + '"'
                parsed = f"coalesce(try_cast({escaped} AS TIMESTAMP),try_strptime(cast({escaped} AS VARCHAR), '%Y%m%d'))"
                low, high, count = con.execute(f"SELECT min({parsed}),max({parsed}),count({parsed}) FROM sample").fetchone()
                if count:
                    content["date_columns"][name] = {"min": str(low), "max": str(high), "nonnull": count}
                    content["reference_column"] = name
                    content["max_reference"] = str(high)
        if item["dataset"] == "cvu-usitermica":
            content["reference_column"] = "dat_fimsemana"
            content["max_reference"] = content["date_columns"]["dat_fimsemana"]["max"]
    heads = [e for item in audit["results"] for e in item.get("endpoints", [])]
    audit["summary"] = {"datasets": len(audit["results"]), "file_urls_tested": len(heads),
                        "http_200": sum(e.get("http_status") == 200 for e in heads),
                        "file_errors": [e for e in heads if e.get("http_status") != 200],
                        "load_api": "Both HTTP 200 but empty without area: acquisition not confirmed"}
    atomic_json(path, audit)
    lines = ["# Endpoints and observed updates", "", f"Consulta UTC: {audit['completed_at']}.", "",
             f"{len(audit['results'])} datasets selected; {len(heads)} recent file URLs tested; {audit['summary']['http_200']} returned HTTP 200.", "",
             "Both load APIs answered HTTP 200 with an empty list in the test without an area. They are not approved for collection until the official code and returned observations are validated.", "",
             "| Dataset | Latest reference read | Result |", "|---|---|---|"]
    for item in audit["results"]:
        content = item.get("content", {})
        label = item["status"]
        if item["dataset"] in cadastral:
            label = "link works; registry update not confirmed"
        # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
        lines.append(f"| [{item['dataset']}](https://dados.ons.org.br/dataset/{item['dataset']}) | {content.get('max_reference') or 'not confirmed / not applicable'} | {label} |")
    lines += ["", "Interpretation: a recent reference is evidence of recent content, not a certification of each product's expected delay. Future dates in schedules, CVU and flood-control volume may represent validity/horizon. Do not confuse them with realised observations. Times stay as delivered by the source, without time-zone conversion.", "", "The associated JSON holds exact URLs, HTTP codes, Last-Modified, hashes and date fields. No conclusion holds for every historical file in the bucket."]
    (ROOT / "docs/inventory/endpoints_audit.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(audit["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
