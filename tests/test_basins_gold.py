"""Médias por bacia, correspondência de nomes e download por faixa de bytes. Sem rede."""
import sys
from io import BytesIO
from pathlib import Path

import geopandas as gpd
import numpy as np
import polars as pl
import pytest
from shapely.geometry import Polygon, box

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import acquire  # noqa: E402
from basins import AREA_CRS, basin_means, ena_mapping, grid_weights, normalize_name  # noqa: E402


def make_basins():
    """Bacia A cobre 2×2 células inteiras; bacia B cobre metade de uma célula."""
    geometry = [box(-50.0, -20.0, -49.8, -19.8), box(-49.8, -20.0, -49.75, -19.9)]
    frame = gpd.GeoDataFrame({"basin_id": [1, 2], "basin_name": ["Grande", "Uatuamã"],
                              "geometry_repaired": [False, False]}, geometry=geometry, crs="EPSG:4326")
    frame["area_km2"] = frame.to_crs(AREA_CRS).area / 1e6
    frame["source_sha256"] = "test"
    return frame


GRID_LATS = np.array([-19.95, -19.85])
GRID_LONS = np.array([-49.95, -49.85, -49.75])


def test_weights_sum_to_one_per_basin(tmp_path):
    weights = grid_weights(GRID_LATS, GRID_LONS, make_basins(), tmp_path)
    totals = dict(weights.group_by("basin_id").agg(pl.col("weight").sum()).iter_rows())
    assert totals[1] == pytest.approx(1.0, abs=1e-6)
    assert totals[2] == pytest.approx(1.0, abs=1e-6)
    # Bacia B ocupa metade da célula (-49.75, -19.95).
    part = weights.filter(pl.col("basin_id") == 2)
    assert part.height == 1 and part["cell_fraction_inside"][0] == pytest.approx(0.5, abs=0.01)
    # Segunda chamada usa o cache em disco.
    assert len(list(tmp_path.glob("*.parquet"))) == 1


def test_area_weighted_mean_ignores_missing_cells_and_reports_coverage(tmp_path):
    basins = make_basins()
    weights = grid_weights(GRID_LATS, GRID_LONS, basins, tmp_path)
    lat, lon = np.meshgrid(GRID_LATS, GRID_LONS, indexing="ij")
    values = [10.0, 20.0, 99.0, 30.0, None, 99.0]  # uma célula da bacia A sem valor
    frame = pl.DataFrame({"latitude": lat.ravel(), "longitude": lon.ravel(), "value": values, "variable": "precipitation_mm"})
    result = {r["basin_id"]: r for r in basin_means(frame, weights, basins, ["variable"]).iter_rows(named=True)}
    # Células de A com valor têm áreas quase iguais: média ≈ (10+20+30)/3, cobertura ≈ 3/4.
    assert result[1]["value"] == pytest.approx(20.0, abs=0.1)
    assert result[1]["coverage"] == pytest.approx(0.75, abs=0.01)
    assert result[1]["basin_name"] == "Grande"
    assert result[2]["value"] == pytest.approx(99.0)


def test_basin_with_no_valid_cells_is_null_not_zero(tmp_path):
    basins = make_basins()
    weights = grid_weights(GRID_LATS, GRID_LONS, basins, tmp_path)
    frame = pl.DataFrame({"latitude": [-19.95], "longitude": [-49.75], "value": [None], "variable": ["p"]},
                         schema_overrides={"value": pl.Float64})
    result = basin_means(frame, weights, basins, ["variable"])
    assert result.filter(pl.col("basin_id") == 2)["value"][0] is None


def test_ena_mapping_uses_normalized_names_and_explicit_overrides_only():
    basins = make_basins()
    mapping = ena_mapping(basins, ["GRANDE", "UATUMA", "PARANA"], {"Uatuamã": "UATUMA"})
    rows = {r["basin_name"]: r for r in mapping.iter_rows(named=True)}
    assert rows["Grande"]["ena_nom_bacia"] == "GRANDE" and rows["Grande"]["match"] == "exact_normalized"
    assert rows["Uatuamã"]["match"] == "manual_spelling"
    assert normalize_name("Paraíba do Sul") == "PARAIBA DO SUL"
    assert normalize_name("Curuá-Una") == "CURUA UNA"
    unmatched = ena_mapping(basins, ["PARANA"], {})
    assert unmatched["ena_nom_bacia"].to_list() == [None, None]


def test_make_valid_repairs_bowtie_without_inventing_area():
    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    assert not bowtie.is_valid
    repaired = gpd.GeoSeries([bowtie]).make_valid()
    assert repaired.is_valid.all()


class RangeResponse(BytesIO):
    def __init__(self, content, status):
        super().__init__(content)
        self.status = status
        self.headers = {"Content-Length": str(len(content)), "Content-Type": "application/octet-stream"}

    def geturl(self):
        return "https://example.org/f.grib2"


def test_ranged_fetch_concatenates_parts(tmp_path, monkeypatch):
    source = b"AAAABBBBCCCCDDDD"
    calls = []

    def fake_open(url, headers=None):
        start, end = map(int, headers["Range"].split("=")[1].split("-"))
        calls.append((start, end))
        return RangeResponse(source[start:end + 1], 206)

    monkeypatch.setattr(acquire, "open_http", fake_open)
    store = acquire.Store(tmp_path)
    try:
        manifest = store.fetch("ecmwf", "x", "r", "https://example.org/f.grib2", ranges=[(4, 4), (12, 4)])
        assert Path(manifest["path"]).read_bytes() == b"BBBBDDDD"
        assert calls == [(4, 7), (12, 15)]
    finally:
        store.close()


def test_ranged_fetch_rejects_server_ignoring_range(tmp_path, monkeypatch):
    monkeypatch.setattr(acquire, "open_http", lambda url, headers=None: RangeResponse(b"WHOLEFILE", 200))
    store = acquire.Store(tmp_path)
    try:
        with pytest.raises(ValueError, match="206"):
            store.fetch("ecmwf", "x", "r", "https://example.org/f.grib2", ranges=[(0, 4)])
    finally:
        store.close()
