# Input: known endpoints and the date 2026-11-08 written in the code. Output: response JSONs and a report.
# A one-off diagnostic: HTTP 200 with an empty list does not prove observations are available.

"""Probe documented load endpoints without guessing official area codes."""
import json
from urllib.parse import urlencode

# Scripts in this subfolder reuse the modules in scripts/ (acquire, pipeline...).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from acquire import DATA_DIR, ROOT, atomic_json, utcnow
from audit_endpoints import request


def main():
    results = []
    for kind in ["programada", "verificada"]:
        url = f"https://apicarga.ons.org.br/prd/carga{kind}?" + urlencode({"dat_inicio": "2026-11-08", "dat_fim": "2026-11-08"})
        result = {"kind": kind, "url": url, "checked_at": utcnow(),
                  "note": "Area omitted deliberately; no official area code was inferred."}
        try:
            with request(url) as response:
                result["http_status"] = response.status
                body = response.read(30_000_001)
                if len(body) > 30_000_000:
                    raise ValueError("Response exceeds 30 MB")
                payload = json.loads(body)
                result["json_type"] = type(payload).__name__
                atomic_json(DATA_DIR / f"endpoint_audit/load_{kind}.json", payload)
                if isinstance(payload, list):
                    result["rows"] = len(payload)
                    result["sample"] = payload[:2]
                elif isinstance(payload, dict):
                    result["keys"] = list(payload)
                    result["envelope_preview"] = str(payload)[:1500]
        except Exception as exc:
            result["error"] = str(exc)
        # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        atomic_json(ROOT / "docs/inventory/load_api_probe.json", results)


if __name__ == "__main__":
    main()
