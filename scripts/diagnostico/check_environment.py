# Input: the active Python environment. Output: docs/environment.json and requirements-lock-windows.txt.
# Temperature and geometry examples are synthetic, used only to check file readers.

"""Verify installed acquisition dependencies and native I/O backends offline."""
import importlib
import importlib.metadata
import json
# Importa platform: identifica sistema operacional e arquitetura.
import platform
import subprocess
import sys
# Importa tempfile: cria pastas de teste removidas ao sair do contexto.
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    # Maps pip name -> import name. Example: beautifulsoup4 is installed but bs4 is imported.
    packages = {
        "duckdb": "duckdb", "numpy": "numpy", "pandas": "pandas", "polars": "polars",
        "pyarrow": "pyarrow", "requests": "requests", "httpx": "httpx", "tenacity": "tenacity",
        "pydantic": "pydantic", "pandera": "pandera.pandas", "beautifulsoup4": "bs4",
        "lxml": "lxml.etree", "openpyxl": "openpyxl", "geopandas": "geopandas",
        "shapely": "shapely", "pyproj": "pyproj", "rasterio": "rasterio",
        "rioxarray": "rioxarray", "xarray": "xarray", "cfgrib": "cfgrib", "eccodes": "eccodes",
        "netCDF4": "netCDF4", "h5netcdf": "h5netcdf", "h5py": "h5py", "dask": "dask.array",
        "fsspec": "fsspec", "s3fs": "s3fs", "boto3": "boto3",
        "ecmwf-opendata": "ecmwf.opendata", "cdsapi": "cdsapi", "jupyterlab": "jupyterlab",
        "ipykernel": "ipykernel", "matplotlib": "matplotlib", "seaborn": "seaborn",
        "plotly": "plotly", "pytest": "pytest", "ruff": "ruff", "pypdf": "pypdf",
    }
    report = {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
              "libraries": {}, "checks": {}, "errors": []}
    for package, module in packages.items():
        try:
            importlib.import_module(module)
            report["libraries"][package] = importlib.metadata.version(package)
        except Exception as exc:
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            report["errors"].append(f"{package}: {exc}")
    with tempfile.TemporaryDirectory() as tmp:
        import numpy as np
        # Importa pandas: manipula tabelas e escreve o Parquet de teste.
        import pandas as pd
        import polars as pl
        import xarray as xr
        import eccodes
        import geopandas as gpd
        import rasterio
        from rasterio.transform import from_origin
        # De shapely.geometry, importa Point: cria geometrias de teste, como pontos.
        from shapely.geometry import Point

        folder = Path(tmp)
        # check: runs a verification function and records pass/fail; one failure does not stop the others.
        def check(name, function):
            try:
                function()
                report["checks"][name] = "passed"
            except Exception as exc:
                report["checks"][name] = "failed"
                # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
                report["errors"].append(f"{name}: {exc}")

        # parquet: writes two synthetic values with Pandas/PyArrow and reads them with Polars, to check local interoperability.
        def parquet():
            path = folder / "data.parquet"
            pd.DataFrame({"value": [1, 2]}).to_parquet(path)
            assert pl.read_parquet(path)["value"].to_list() == [1, 2]

        # netcdf: writes and reads a small dataset with two NetCDF backends and compares the values.
        def netcdf():
            dataset = xr.Dataset({"temperature": ("x", [20.0, 21.0])})
            for engine in ["netcdf4", "h5netcdf"]:
                path = folder / f"{engine}.nc"
                dataset.to_netcdf(path, engine=engine)
                with xr.open_dataset(path, engine=engine) as actual:
                    np.testing.assert_array_equal(actual.temperature.values, [20.0, 21.0])

        # grib: creates a sample GRIB message with ecCodes and opens it with xarray/cfgrib, confirming the native library.
        def grib():
            path = folder / "sample.grib2"
            handle = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
            try:
                with path.open("wb") as output:
                    eccodes.codes_write(handle, output)
            finally:
                # Release the message allocated in the native library; needed even when writing fails.
                eccodes.codes_release(handle)
            with xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""}) as dataset:
                assert dataset.data_vars

        # vector: writes a synthetic point to GeoPackage and reads it back with GeoPandas/GDAL.
        def vector():
            path = folder / "geometry.gpkg"
            gpd.GeoDataFrame({"id": [1]}, geometry=[Point(-45, -20)], crs="EPSG:4326").to_file(path)
            assert len(gpd.read_file(path)) == 1

        # raster: writes a small GeoTIFF grid and checks the pixel sum after reading it back.
        def raster():
            path = folder / "sample.tif"
            with rasterio.open(path, "w", driver="GTiff", height=2, width=2, count=1,
                               dtype="float32", crs="EPSG:4326", transform=from_origin(-45, -20, .1, .1)) as output:
                output.write(np.ones((1, 2, 2), dtype="float32"))
            with rasterio.open(path) as source:
                assert source.read().sum() == 4

        check("parquet_pandas_pyarrow_polars", parquet)
        check("netcdf_backends", netcdf)
        check("grib_eccodes_cfgrib", grib)
        check("vector_geopandas_gdal", vector)
        check("raster_rasterio_gdal", raster)
    result = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
    report["checks"]["pip_check"] = result.stdout.strip() or result.stderr.strip()
    if result.returncode:
        # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
        report["errors"].append("pip check failed")
    frozen = subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"], capture_output=True, text=True, check=True)
    (ROOT / "requirements-lock-windows.txt").write_text(frozen.stdout, encoding="utf-8")
    (ROOT / "docs/environment.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
