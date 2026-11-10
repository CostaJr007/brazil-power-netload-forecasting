"""Descobre arquivos meteorológicos oficiais e inspeciona polígonos ONS locais.

Executar usa rede para obter listagens; não baixa o histórico meteorológico.
"""
# As listagens HTML oficiais servem como catálogo quando não há API de arquivos.
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin

import geopandas as gpd

# Reutilizamos caminhos, escrita de relatórios e a política HTTP do projeto.
from acquire import DATA_DIR, ROOT, atomic_json, open_http, utcnow


class Links(HTMLParser):
    """Extrai apenas href; não executa JavaScript de páginas externas."""

    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.urls.append(href)


def listing(url):
    """Preserva uma listagem e devolve os links resolvidos contra sua URL."""
    with open_http(url, timeout=30) as response:
        body = response.read(5_000_001)
        if len(body) > 5_000_000:
            raise ValueError("Listagem excede 5 MB")
        encoding = response.headers.get_content_charset() or "utf-8"
        headers = dict(response.headers.items())
    # Esse HTML é evidência de descoberta, não um arquivo de observações.
    digest = hashlib.sha256(body).hexdigest()
    folder = DATA_DIR / "weather_catalog"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (digest + ".html")).write_bytes(body)
    atomic_json(folder / (digest + ".manifest.json"),
                {"url": url, "ingested_at": utcnow(), "sha256": digest, "headers": headers})
    parser = Links()
    parser.feed(body.decode(encoding, errors="replace"))
    return sorted(set(urljoin(url, href) for href in parser.urls))


def basin_inventory():
    """Lê o shapefile preservado na Bronze e descreve CRS, nomes e geometrias."""
    evidence = json.loads((ROOT / "docs/inventory/acquisition_validation.json").read_text(encoding="utf-8"))
    manifest = next(i["manifest"] for i in evidence["checks"] if i["dataset"] == "bacia_contorno")
    # GDAL precisa reconhecer .zip no nome. A Bronze usa apenas hash; criamos
    # uma cópia de acesso com extensão, sem modificar o objeto original.
    spatial = DATA_DIR / "geography" / (manifest["sha256"] + ".zip")
    spatial.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest["path"], spatial)
    frame = gpd.read_file("zip://" + spatial.as_posix())
    if frame.crs is None:
        raise ValueError("Polígonos sem CRS documentado")
    frame = frame.to_crs("EPSG:4326")
    # A inspeção não corrige geometrias da fonte silenciosamente.
    rows = []
    for index, row in frame.iterrows():
        geometry = row.geometry
        attributes = {str(k): str(v) for k, v in row.items() if k != frame.geometry.name}
        rows.append({"row_id": int(index), "attributes": attributes,
                     "geometry_type": geometry.geom_type if geometry is not None else None,
                     "valid": bool(geometry is not None and geometry.is_valid),
                     "bbox": list(geometry.bounds) if geometry is not None else None})
    return {"source_manifest": manifest, "access_copy": str(spatial), "crs": str(frame.crs),
            "columns": list(frame.columns), "features": len(frame),
            "invalid_features": int((~frame.geometry.is_valid).sum()),
            "bbox": list(frame.total_bounds), "basins": rows}


def main():
    """Salva o inventário espacial e os arquivos realmente anunciados nas fontes."""
    now = datetime.now(timezone.utc)
    report = {"checked_at": utcnow(), "basins": basin_inventory(), "sources": {}, "errors": []}
    urls = {
        "merge_root": "https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/",
        "merge_month": f"https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/{now:%Y/%m}/",
        "gfs_root": "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/",
        "inmet": "https://portal.inmet.gov.br/dadoshistoricos",
    }
    for name, url in urls.items():
        try:
            links = listing(url)
            # Guardamos os links relevantes sem reconstruir nomes de arquivo presumidos.
            if name == "merge_month":
                links = [u for u in links if re.search(r"MERGE_CPTEC_\d{8}\.(grib2|ctl)$", u)]
            elif name == "inmet":
                links = [u for u in links if ".zip" in u.lower()]
            elif name == "gfs_root":
                links = [u for u in links if re.search(r"/gfs\.\d{8}/$", u)]
            report["sources"][name] = {"url": url, "links": links, "count": len(links)}
            print(f"OK {name}: {len(links)} links", flush=True)
        except Exception as exc:
            report["errors"].append({"source": name, "url": url, "error": str(exc)})
    atomic_json(ROOT / "docs/inventory/weather_discovery.json", report)
    print(json.dumps({"features": report["basins"]["features"], "columns": report["basins"]["columns"],
                      "invalid": report["basins"]["invalid_features"], "bbox": report["basins"]["bbox"],
                      "example_basins": report["basins"]["basins"][:3], "errors": report["errors"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
