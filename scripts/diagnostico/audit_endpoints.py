# Input: configs/ons.json and the remote catalog. Output: data/endpoint_audit and a report in docs/inventory.
# Note: running this file makes new requests and replaces the latest audit report.

"""Live endpoint and latest-reference audit for the curated ONS selection.

Does not claim historical completeness or physical correctness.
"""
import concurrent.futures
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import duckdb

# Scripts in this subfolder reuse the modules in scripts/ (acquire, pipeline...).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from acquire import DATA_DIR, ROOT, atomic_json, json_get, utcnow


# resource_date: approximate date from the resource name/URL, to pick the most recent file (a heuristic; records confirm it).
def resource_date(resource):
    text = resource.get("url", "") + " " + resource.get("name", "")
    matches = re.findall(r"(20\d{2})(?:[-_](\d{2}))?(?:[-_](\d{2}))?", text)
    return max(((int(y), int(m or 1), int(d or 1)) for y, m, d in matches), default=(0, 0, 0))


# request: opens a response for a URL and HTTP method with a timeout (HEAD for headers, GET for content); no retry policy.
def request(url, method="GET"):
    return urlopen(Request(url, method=method, headers={"User-Agent": "EnergyDataStudy/0.1"}), timeout=30)


# head: HTTP status and headers of a resource, or the error. Does not read records; Last-Modified describes the HTTP object.
def head(resource):
    result = {"resource_id": resource["id"], "format": resource.get("format"), "url": resource["url"]}
    try:
        with request(resource["url"], "HEAD") as response:
            result.update(http_status=response.status, content_length=response.headers.get("Content-Length"),
                          last_modified=response.headers.get("Last-Modified"), final_url=response.geturl())
    except Exception as exc:
        result["error"] = str(exc)
    return result


# inspect_file: downloads a recent resource up to the size limit and inspects schema/dates with DuckDB, in a scratch audit area (not the versioned Bronze).
def inspect_file(resource):
    fmt = resource["format"].upper()
    if fmt not in {"CSV", "PARQUET"}:
        return {"status": "non_temporal_resource", "format": fmt}
    target_dir = DATA_DIR / "endpoint_audit"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / (hashlib.sha256(resource["url"].encode()).hexdigest() + "." + fmt.lower())
    digest = hashlib.sha256()
    size = 0
    temp = path.with_suffix(path.suffix + ".part")
    try:
        with request(resource["url"]) as response, temp.open("wb") as output:
            length = response.headers.get("Content-Length")
            if length and int(length) > 100_000_000:
                return {"status": "size_limit", "bytes_declared": int(length)}
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > 100_000_000:
                    raise ValueError("Size limit: 100 MB")
                digest.update(block)
                output.write(block)
            if length and size != int(length):
                raise ValueError("Incomplete payload")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    con = duckdb.connect(config={"threads": 1, "memory_limit": "512MB"})
    try:
        relation = con.read_parquet(str(path)) if fmt == "PARQUET" else con.read_csv(str(path), delimiter=";", sample_size=-1)
        relation.create_view("sample")
        schema = con.execute("DESCRIBE sample").fetchall()
        dates = {}
        for name, datatype, *_ in schema:
            if "TIMESTAMP" in datatype or datatype == "DATE" or re.match(r"^(din_|dat_|ear_data$|ena_data$)", name):
                escaped = '"' + name.replace('"', '""') + '"'
                parsed = f"coalesce(try_cast({escaped} AS TIMESTAMP),try_strptime(cast({escaped} AS VARCHAR), ['%Y%m%d', '%d/%m/%Y', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M']))"
                values = con.execute(f"SELECT min({parsed}), max({parsed}), count({parsed}) FROM sample").fetchone()
                if values[2]:
                    dates[name] = {"min": str(values[0]), "max": str(values[1]), "nonnull": values[2]}
        preferred = ["din_instante", "din_referenciautc", "dat_referencia", "ear_data", "ena_data", "din_data", "din_programacaodia", "dat_programacao", "din_medicao", "dat_fimsemana", "din_inicioperiodo", "din_fimperiodo"]
        reference = next((name for name in preferred if name in dates), None)
        return {"status": "readable", "bytes": size, "sha256": digest.hexdigest(), "path": str(path),
                "rows": con.execute("SELECT count(*) FROM sample").fetchone()[0],
                "date_columns": dates, "reference_column": reference,
                "max_reference": dates[reference]["max"] if reference else None,
                "columns": [{"name": r[0], "type": r[1]} for r in schema]}
    finally:
        con.close()


# audit: selects recent resources of a CKAN dataset, tests their links and inspects a preferred format. Observation APIs are left pending for a specific test.
def audit(package):
    result = {"dataset": package["name"], "title": package["title"], "checked_at": utcnow()}
    resources = [r for r in package.get("resources", [])
                 if str(r.get("format", "")).upper() in {"CSV", "PARQUET", "ZIP", "API"}
                 and not re.search(r"dicion.rio|dictionary", str(r.get("name", "")), re.I)]
    apis = [r for r in resources if str(r.get("format")).upper() == "API"]
    if apis:
        result["status"] = "api_observation_test_pending"
        result["api_descriptions"] = [r.get("description") for r in apis]
        return result
    if not resources:
        result["status"] = "no_supported_resource"
        return result
    # File-name reference wins over metadata_updated, which can refer to an old file.
    newest = max(resource_date(r) for r in resources)
    candidates = [r for r in resources if resource_date(r) == newest]
    # De-duplicate endpoints repeated in the catalogue.
    candidates = list({r["url"]: r for r in candidates}.values())
    result["latest_label_date"] = newest
    result["endpoints"] = [head(r) for r in candidates]
    preferred = sorted(candidates, key=lambda r: {"PARQUET": 0, "CSV": 1, "ZIP": 2}.get(str(r.get("format")).upper(), 3))[0]
    result["inspected_url"] = preferred["url"]
    try:
        result["content"] = inspect_file(preferred)
        result["status"] = result["content"]["status"]
    except Exception as exc:
        result.update(status="content_error", error=str(exc))
    return result


def main():
    selected = json.loads((ROOT / "configs/ons.json").read_text(encoding="utf-8"))["selected"]
    packages, errors = [], []
    for name in selected:
        try:
            payload = json_get("https://dados.ons.org.br/api/3/action/package_show?id=" + name)
            if not payload.get("success"):
                raise ValueError(str(payload))
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            packages.append(payload["result"])
        except Exception as exc:
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            errors.append({"dataset": name, "status": "catalog_error", "error": str(exc)})
    result = {"started_at": utcnow(), "scope": "Newest dated resources per selected dataset; not every historical URL",
              "results": errors, "freshness_note": "Reference dates are reported, not a cadence/SLA guarantee. Cadastral tables may have no operational reference date."}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(audit, p): p["name"] for p in packages}
        for future in concurrent.futures.as_completed(futures):
            try:
                item = future.result()
            except Exception as exc:
                item = {"dataset": futures[future], "status": "audit_error", "error": str(exc)}
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            result["results"].append(item)
            atomic_json(ROOT / "docs/inventory/endpoints_audit.json", result)
            print(json.dumps({"dataset": item["dataset"], "status": item["status"],
                              "max_reference": item.get("content", {}).get("max_reference"),
                              "error": item.get("error")}, ensure_ascii=False), flush=True)
    result["completed_at"] = utcnow()
    result["results"].sort(key=lambda row: row["dataset"])
    atomic_json(ROOT / "docs/inventory/endpoints_audit.json", result)
    lines = ["# Auditoria dos endpoints recentes do ONS", "", f"Run UTC: {result['completed_at']}", "",
             "Scope: most recent resources identified by name/URL in the 39 selected datasets. Does not test every historical file.", "",
             "Dates below were read from the records. Last-Modified is recorded separately in the JSON. A missing date does not make a registry invalid.", "",
             "| Dataset | Read status | Latest reference in the records | HTTP of recent links |", "|---|---|---|---|"]
    for item in result["results"]:
        states = ", ".join(str(e.get("http_status", e.get("error"))) for e in item.get("endpoints", []))
        # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
        lines.append(f"| [{item['dataset']}](https://dados.ons.org.br/dataset/{item['dataset']}) | {item['status']} | {item.get('content', {}).get('max_reference') or 'not confirmed'} | {states or 'pending'} |")
    (ROOT / "docs/inventory/endpoints_audit.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
