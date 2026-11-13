"""Measure when each ONS dataset actually changes, from the Last-Modified headers stored in Bronze.

Each real file revision becomes an observation. More collection days make it more reliable;
with few days, the times only reflect what has been seen so far. Writes docs/inventory/horarios_publicacao.json.

Run: .\\.venv\\Scripts\\python.exe scripts/horarios_publicacao.py
"""
import json
from pathlib import Path

import pandas as pd

from acquire import DATA_DIR, ROOT


def ler_manifestos(pasta):
    linhas = []
    for caminho in Path(pasta).glob("*/*/*.manifest.json"):
        manifesto = json.loads(caminho.read_text(encoding="utf-8"))
        cabecalhos = {str(k).lower(): v for k, v in (manifesto.get("headers") or {}).items()}
        linhas.append({"conjunto": manifesto.get("dataset"), "recurso": manifesto.get("resource_id"), "sha256": manifesto.get("sha256"),
                       "ultima_modificacao": cabecalhos.get("last-modified")})
    return pd.DataFrame(linhas)


def resumir(manifestos):
    """One observation per distinct content of each resource; re-downloading does not count as publication."""
    d = manifestos.copy()
    d["ultima_modificacao"] = pd.to_datetime(d["ultima_modificacao"], utc=True, errors="coerce")
    d = d.dropna(subset=["ultima_modificacao"]).drop_duplicates(["conjunto", "recurso", "sha256"])
    d["local"] = d["ultima_modificacao"].dt.tz_convert("America/Sao_Paulo")
    saida = {}
    for conjunto, g in d.groupby("conjunto"):
        horas = g["local"].dt.hour.value_counts().sort_index()
        saida[conjunto] = {"revisoes": len(g), "dias_observados": int(g["local"].dt.normalize().nunique()),
                           "primeira": str(g["local"].min()), "ultima": str(g["local"].max()),
                           "revisoes_por_hora_local": {int(h): int(n) for h, n in horas.items()}}
    return saida


def main():
    resultado = resumir(ler_manifestos(DATA_DIR / "bronze/ons"))
    (ROOT / "docs/inventory/horarios_publicacao.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for conjunto, r in sorted(resultado.items()):
        print(f"{conjunto:48s} rev={r['revisoes']:4d} days={r['dias_observados']:3d} hours={r['revisoes_por_hora_local']}")


if __name__ == "__main__":
    main()
