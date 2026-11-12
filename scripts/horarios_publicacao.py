"""Mede em que horário cada conjunto do ONS realmente muda, a partir do Last-Modified guardado na Bronze.

Cada revisão real do arquivo vira uma observação. Quanto mais dias de coleta, mais confiável fica;
com poucos dias, os horários indicam só o que foi visto até agora. Grava docs/inventory/horarios_publicacao.json.

Executar: .\\.venv\\Scripts\\python.exe scripts/horarios_publicacao.py
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
    """Uma observação por conteúdo distinto de cada recurso; repetir o download não conta como publicação."""
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
        print(f"{conjunto:48s} rev={r['revisoes']:4d} dias={r['dias_observados']:3d} horas={r['revisoes_por_hora_local']}")


if __name__ == "__main__":
    main()
