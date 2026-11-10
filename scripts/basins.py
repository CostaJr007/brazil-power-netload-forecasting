"""Médias meteorológicas por BACIA hidrográfica (polígonos oficiais do ONS).

Por que não usar o centróide ou o retângulo da bacia?
Uma bacia como a do Madeira tem 1,5 milhão de km²: chover no centro não diz
nada sobre o resto. A média correta pondera cada célula da grade pela área
que ela tem DENTRO do polígono:

    chuva_bacia = Σ (chuva_célula × área_célula∩bacia) / Σ área_célula∩bacia

As áreas são calculadas em projeção de área (EPSG:5880, SIRGAS 2000 / Brazil
Polyconic), não em graus: 1° de longitude encolhe à medida que se afasta do
Equador.

Reparo de geometrias: 6 das 31 feições do arquivo do ONS têm autointerseções
minúsculas. shapely.make_valid corrige sem mudar a área (variação medida:
0,000%). O arquivo original na Bronze continua intacto; o reparo é registrado
em cada linha (geometry_repaired).
"""
import hashlib
import json
import unicodedata
from pathlib import Path

import geopandas as gpd
import numpy as np
import polars as pl
import shapely

from acquire import ROOT, resolve_data_path

AREA_CRS = "EPSG:5880"


def normalize_name(value):
    """'Paraíba do Sul' → 'PARAIBA DO SUL'; usado só para casar nomes entre fontes."""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return " ".join(text.upper().replace("-", " ").split())


def load_basins():
    """Lê os polígonos do ONS, repara geometrias inválidas e calcula a área de cada bacia."""
    discovery = json.loads((ROOT / "docs/inventory/weather_discovery.json").read_text(encoding="utf-8"))
    # Caminho absoluto gravado na descoberta; resolve_data_path reencontra se data/ mudou de lugar.
    path = str(resolve_data_path(discovery["basins"]["access_copy"]))
    frame = gpd.read_file("zip://" + path)
    if frame.crs is None or frame.crs.to_epsg() != 4326:
        raise ValueError(f"CRS inesperado nos polígonos: {frame.crs}")
    repaired = ~frame.is_valid
    geometry = frame.geometry.make_valid()
    # make_valid pode devolver GeometryCollection com linhas soltas; só áreas importam.
    geometry = geometry.apply(lambda g: shapely.unary_union([p for p in getattr(g, "geoms", [g])
                                                            if p.geom_type in ("Polygon", "MultiPolygon")]))
    basins = gpd.GeoDataFrame({"basin_id": frame["ID"].astype(int), "basin_name": frame["Nome_Bacia"],
                               "geometry_repaired": repaired.values}, geometry=geometry.values, crs="EPSG:4326")
    basins["area_km2"] = basins.to_crs(AREA_CRS).area / 1e6
    basins["source_sha256"] = Path(path).stem
    return basins


def grid_signature(lats, lons, basins):
    """Identidade da grade + polígonos; pesos são reaproveitados enquanto ela não mudar."""
    payload = json.dumps([np.round(lats, 4).tolist(), np.round(lons, 4).tolist(), basins["source_sha256"].iloc[0]])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def grid_weights(lats, lons, basins, cache_dir=None):
    """Peso de cada célula em cada bacia: área(célula ∩ bacia) / área(bacia).

    lats/lons são os CENTROS das células de uma grade regular. A soma dos pesos
    de uma bacia é ~1 quando a grade cobre a bacia inteira.
    """
    lats = np.unique(np.round(np.asarray(lats, dtype=float), 4))
    lons = np.unique(np.round(np.asarray(lons, dtype=float), 4))
    signature = grid_signature(lats, lons, basins)
    cache = Path(cache_dir) / f"{signature}.parquet" if cache_dir else None
    if cache and cache.exists():
        return pl.read_parquet(cache)
    half_lat = float(np.median(np.diff(lats))) / 2
    half_lon = float(np.median(np.diff(lons))) / 2
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    lon_flat, lat_flat = lon_grid.ravel(), lat_grid.ravel()
    cells = gpd.GeoDataFrame({"latitude": lat_flat, "longitude": lon_flat},
                             geometry=shapely.box(lon_flat - half_lon, lat_flat - half_lat,
                                                  lon_flat + half_lon, lat_flat + half_lat), crs="EPSG:4326")
    pairs = gpd.sjoin(cells, basins[["basin_id", "geometry"]], predicate="intersects", how="inner")
    pieces = shapely.intersection(pairs.geometry.values, basins.geometry.loc[pairs["index_right"]].values)
    area = gpd.GeoSeries(pieces, crs="EPSG:4326").to_crs(AREA_CRS).area.values / 1e6
    cell_area = gpd.GeoSeries(pairs.geometry.values, crs="EPSG:4326").to_crs(AREA_CRS).area.values / 1e6
    basin_area = basins.set_index("basin_id").loc[pairs["basin_id"], "area_km2"].values
    weights = pl.DataFrame({"basin_id": pairs["basin_id"].values, "lat_key": np.round(pairs["latitude"].values, 3),
                            "lon_key": np.round(pairs["longitude"].values, 3), "overlap_km2": area,
                            "cell_fraction_inside": area / cell_area, "weight": area / basin_area})
    weights = weights.filter(pl.col("overlap_km2") > 0)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        weights.write_parquet(cache)
    return weights


def basin_means(frame, weights, basins, keys):
    """Média ponderada por bacia; células sem valor (null) saem do numerador E do denominador.

    coverage = fração da área da bacia com valor válido (1,0 = bacia toda coberta).
    Não imputamos ausências: se coverage for baixo, quem consome decide se usa.
    """
    names = pl.DataFrame({"basin_id": basins["basin_id"].tolist(), "basin_name": basins["basin_name"].tolist()})
    data = frame.with_columns(pl.col("latitude").round(3).alias("lat_key"), pl.col("longitude").round(3).alias("lon_key"))
    joined = data.join(weights.select("basin_id", "lat_key", "lon_key", "weight"), on=["lat_key", "lon_key"], how="inner")
    has_value = pl.col("value").is_not_null()
    result = (joined.with_columns(pl.when(has_value).then(pl.col("value") * pl.col("weight")).otherwise(0.0).alias("_wv"),
                                  pl.when(has_value).then(pl.col("weight")).otherwise(0.0).alias("_w"))
              .group_by(["basin_id", *keys])
              .agg((pl.col("_wv").sum() / pl.col("_w").sum()).alias("value"), pl.col("_w").sum().alias("coverage"),
                   pl.len().alias("cells")))
    # Bacia sem nenhuma célula válida fica com value null (0/0), nunca zero.
    result = result.with_columns(pl.when(pl.col("coverage") > 0).then(pl.col("value")).otherwise(None).alias("value"))
    return result.join(names, on="basin_id", how="left")


def ena_mapping(basins, ena_names, overrides):
    """Liga polígono ↔ nome de bacia usado nas séries de ENA/EAR do ONS.

    Só aceita correspondência por nome normalizado ou por exceção explícita
    (overrides, com justificativa em configs). Sem correspondência = None: não
    adivinhamos que um polígono pequeno pertence a uma bacia maior.
    """
    available = {normalize_name(n): n for n in ena_names}
    rows = []
    for basin_id, name in zip(basins["basin_id"], basins["basin_name"]):
        if name in overrides:
            target, kind = overrides[name], "manual_spelling"
        elif normalize_name(name) in available:
            target, kind = available[normalize_name(name)], "exact_normalized"
        else:
            target, kind = None, "none"
        rows.append({"basin_id": int(basin_id), "basin_name": name, "ena_nom_bacia": target, "match": kind})
    return pl.DataFrame(rows)
