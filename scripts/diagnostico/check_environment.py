# GUIA DE LEITURA — Confere instalação e funcionamento das bibliotecas com pequenos arquivos temporários.
# Entrada: ambiente Python ativo. Saída: docs/environment.json e requirements-lock-windows.txt.
# Os exemplos de temperatura e geometria são sintéticos, usados apenas para verificar leitores de arquivo.
# Comentários não executam; a indentação do código define quais instruções pertencem a cada bloco.

"""Verify installed acquisition dependencies and native I/O backends offline."""
# Importa importlib: importa módulos por nome ou caminho.
import importlib
# Importa importlib.metadata: biblioteca usada pelas operações deste script.
import importlib.metadata
# Importa json: converte entre texto JSON e estruturas Python.
import json
# Importa platform: identifica sistema operacional e arquitetura.
import platform
# Importa subprocess: executa comandos auxiliares no mesmo interpretador.
import subprocess
# Importa sys: acessa o interpretador atual e a saída de erros.
import sys
# Importa tempfile: cria pastas de teste removidas ao sair do contexto.
import tempfile
# De pathlib, importa Path: constrói caminhos de arquivos de forma portátil.
from pathlib import Path

# Define ROOT: a raiz do projeto: parte do caminho deste arquivo, resolve seu endereço absoluto e sobe até a pasta Energy.
ROOT = Path(__file__).resolve().parents[2]


# FUNÇÃO main — coordena a sequência descrita no cabeçalho deste arquivo.
# Recebe parâmetros pelo terminal ou pelos arquivos indicados; os detalhes são explicados nos blocos abaixo.
def main():
    # Mapeia nome no pip -> nome do import. Exemplo: beautifulsoup4 é instalado, mas bs4 é importado.
    packages = {
        # Continua o dicionário: define os campos duckdb, numpy, pandas, polars; cada valor vem da expressão após os dois-pontos.
        "duckdb": "duckdb", "numpy": "numpy", "pandas": "pandas", "polars": "polars",
        # Continua o dicionário: define os campos pyarrow, requests, httpx, tenacity; cada valor vem da expressão após os dois-pontos.
        "pyarrow": "pyarrow", "requests": "requests", "httpx": "httpx", "tenacity": "tenacity",
        # Continua o dicionário: define os campos pydantic, pandera, beautifulsoup4; cada valor vem da expressão após os dois-pontos.
        "pydantic": "pydantic", "pandera": "pandera.pandas", "beautifulsoup4": "bs4",
        # Continua o dicionário: define os campos lxml, openpyxl, geopandas; cada valor vem da expressão após os dois-pontos.
        "lxml": "lxml.etree", "openpyxl": "openpyxl", "geopandas": "geopandas",
        # Continua o dicionário: define os campos shapely, pyproj, rasterio; cada valor vem da expressão após os dois-pontos.
        "shapely": "shapely", "pyproj": "pyproj", "rasterio": "rasterio",
        # Continua o dicionário: define os campos rioxarray, xarray, cfgrib, eccodes; cada valor vem da expressão após os dois-pontos.
        "rioxarray": "rioxarray", "xarray": "xarray", "cfgrib": "cfgrib", "eccodes": "eccodes",
        # Continua o dicionário: define os campos netCDF4, h5netcdf, h5py, dask; cada valor vem da expressão após os dois-pontos.
        "netCDF4": "netCDF4", "h5netcdf": "h5netcdf", "h5py": "h5py", "dask": "dask.array",
        # Continua o dicionário: define os campos fsspec, s3fs, boto3; cada valor vem da expressão após os dois-pontos.
        "fsspec": "fsspec", "s3fs": "s3fs", "boto3": "boto3",
        # Continua o dicionário: define os campos ecmwf-opendata, cdsapi, jupyterlab; cada valor vem da expressão após os dois-pontos.
        "ecmwf-opendata": "ecmwf.opendata", "cdsapi": "cdsapi", "jupyterlab": "jupyterlab",
        # Continua o dicionário: define os campos ipykernel, matplotlib, seaborn; cada valor vem da expressão após os dois-pontos.
        "ipykernel": "ipykernel", "matplotlib": "matplotlib", "seaborn": "seaborn",
        # Continua o dicionário: define os campos plotly, pytest, ruff; cada valor vem da expressão após os dois-pontos.
        "plotly": "plotly", "pytest": "pytest", "ruff": "ruff", "pypdf": "pypdf",
    }
    # Define report: o relatório local que reúne métricas e falhas sem alterar os dados originais.
    report = {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
              # Continua o dicionário: define os campos libraries, checks, errors; cada valor vem da expressão após os dois-pontos.
              "libraries": {}, "checks": {}, "errors": []}
    # Laço: para cada elemento de packages.items(), associa o valor a (package, module) e executa o bloco indentado.
    for package, module in packages.items():
        # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
        try:
            # Executa a operação importlib.import_module(module); seu efeito é descrito pela função ou pelo bloco em que aparece.
            importlib.import_module(module)
            # Registra/atualiza o campo package em report['libraries']; calcula a expressão à direita antes de atribuir seu resultado.
            report["libraries"][package] = importlib.metadata.version(package)
        # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
        except Exception as exc:
            # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
            report["errors"].append(f"{package}: {exc}")
    # Abre um contexto com tempfile.TemporaryDirectory().
    # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
    with tempfile.TemporaryDirectory() as tmp:
        # Importa numpy: cria pequenas matrizes e compara valores numéricos.
        import numpy as np
        # Importa pandas: manipula tabelas e escreve o Parquet de teste.
        import pandas as pd
        # Importa polars: lê o Parquet de teste por uma biblioteca diferente.
        import polars as pl
        # Importa xarray: representa grades meteorológicas e abre GRIB/NetCDF.
        import xarray as xr
        # Importa eccodes: cria e decodifica mensagens meteorológicas GRIB.
        import eccodes
        # Importa geopandas: lê geometrias e trabalha com sistemas de coordenadas.
        import geopandas as gpd
        # Importa rasterio: lê e escreve rasters, como GeoTIFF.
        import rasterio
        # De rasterio.transform, importa from_origin: relaciona posição dos pixels e coordenadas geográficas.
        from rasterio.transform import from_origin
        # De shapely.geometry, importa Point: cria geometrias de teste, como pontos.
        from shapely.geometry import Point

        # Define folder: a pasta da operação; no coletor, origem/dataset/recurso separam os arquivos.
        folder = Path(tmp)
        # FUNÇÃO check — Recebe nome e função de verificação; executa a função e registra passou/falhou. Uma falha não impede as demais verificações de serem tentadas.
        def check(name, function):
            # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
            try:
                # Executa a operação function(); seu efeito é descrito pela função ou pelo bloco em que aparece.
                function()
                # Registra/atualiza o campo name em report['checks']; usa o valor literal 'passed'.
                report["checks"][name] = "passed"
            # Captura a falha do tipo indicado e a associa a exc/error quando solicitado; os detalhes são preservados no relatório.
            except Exception as exc:
                # Registra/atualiza o campo name em report['checks']; usa o valor literal 'failed'.
                report["checks"][name] = "failed"
                # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
                report["errors"].append(f"{name}: {exc}")

        # FUNÇÃO parquet — Grava dois valores sintéticos em Parquet via Pandas/PyArrow e os lê via Polars. O objetivo é conferir interoperabilidade local.
        def parquet():
            # Define path: o caminho local do arquivo usado nesta etapa.
            path = folder / "data.parquet"
            # Executa a operação pd.DataFrame({'value': [1, 2]}).to_parquet(path); seu efeito é descrito pela função ou pelo bloco em que aparece.
            pd.DataFrame({"value": [1, 2]}).to_parquet(path)
            # Verifica a condição pl.read_parquet(path)['value'].to_list() == [1, 2]; se falsa, o teste falha com AssertionError.
            assert pl.read_parquet(path)["value"].to_list() == [1, 2]

        # FUNÇÃO netcdf — Grava e lê um pequeno dataset usando dois leitores NetCDF. Compara os valores após a leitura; não usa dados meteorológicos externos.
        def netcdf():
            # Define dataset: o identificador da fonte ou pequeno dataset de teste, conforme a expressão.
            dataset = xr.Dataset({"temperature": ("x", [20.0, 21.0])})
            # Laço: para cada elemento de ['netcdf4', 'h5netcdf'], associa o valor a engine e executa o bloco indentado.
            for engine in ["netcdf4", "h5netcdf"]:
                # Define path: o caminho local do arquivo usado nesta etapa.
                path = folder / f"{engine}.nc"
                # Grava o dataset sintético com o backend NetCDF indicado para testar seu funcionamento.
                dataset.to_netcdf(path, engine=engine)
                # Abre um contexto com xr.open_dataset(path, engine=engine).
                # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
                with xr.open_dataset(path, engine=engine) as actual:
                    # Executa a operação np.testing.assert_array_equal(actual.temperature.values, [20.0, 21.0]); seu efeito é descrito pela função ou pelo bloco em que aparece.
                    np.testing.assert_array_equal(actual.temperature.values, [20.0, 21.0])

        # FUNÇÃO grib — Cria uma mensagem GRIB de exemplo com ecCodes e tenta abri-la com xarray/cfgrib. Confirma também a disponibilidade da biblioteca nativa.
        def grib():
            # Define path: o caminho local do arquivo usado nesta etapa.
            path = folder / "sample.grib2"
            # Define handle: o identificador de uma mensagem GRIB criado pela biblioteca nativa ecCodes.
            handle = eccodes.codes_grib_new_from_samples("regular_ll_sfc_grib2")
            # Inicia uma operação protegida: except trata falhas; finally, quando presente, executa a finalização mesmo com erro.
            try:
                # Abre um contexto com path.open('wb').
                # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
                with path.open("wb") as output:
                    # Executa a operação eccodes.codes_write(handle, output); seu efeito é descrito pela função ou pelo bloco em que aparece.
                    eccodes.codes_write(handle, output)
            # Finalização obrigatória: este bloco roda com sucesso, return ou exceção; é onde liberamos recursos.
            finally:
                # Libera a mensagem alocada na biblioteca nativa; necessário mesmo quando a escrita falha.
                eccodes.codes_release(handle)
            # Abre um contexto com xr.open_dataset(path, engine='cfgrib', backend_kwargs={'indexpath': ''}).
            # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
            with xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""}) as dataset:
                # Verifica a condição dataset.data_vars; se falsa, o teste falha com AssertionError.
                assert dataset.data_vars

        # FUNÇÃO vector — Grava um ponto sintético em GeoPackage e verifica a leitura com GeoPandas/GDAL. A coordenada serve apenas ao teste.
        def vector():
            # Define path: o caminho local do arquivo usado nesta etapa.
            path = folder / "geometry.gpkg"
            # Executa a operação gpd.GeoDataFrame({'id': [1]}, geometry=[Point(-45, -20)], crs='EPSG:4326').to_file(path); seu efeito é descrito pela função ou pelo bloco em que aparece.
            gpd.GeoDataFrame({"id": [1]}, geometry=[Point(-45, -20)], crs="EPSG:4326").to_file(path)
            # Verifica a condição len(gpd.read_file(path)) == 1; se falsa, o teste falha com AssertionError.
            assert len(gpd.read_file(path)) == 1

        # FUNÇÃO raster — Grava uma pequena grade GeoTIFF e verifica a soma dos pixels após a leitura. Confirma a escrita/leitura do backend raster.
        def raster():
            # Define path: o caminho local do arquivo usado nesta etapa.
            path = folder / "sample.tif"
            # Abre um contexto com rasterio.open(path, 'w', driver='GTiff', height=2, width=2, count=1, dtype='float32', crs='EPSG:4326', transform=from_origin(-45, -20, 0.1, 0.1)).
            # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
            with rasterio.open(path, "w", driver="GTiff", height=2, width=2, count=1,
                               dtype="float32", crs="EPSG:4326", transform=from_origin(-45, -20, .1, .1)) as output:
                # Grava o bloco de bytes no arquivo aberto; não interpreta nem modifica os registros.
                output.write(np.ones((1, 2, 2), dtype="float32"))
            # Abre um contexto com rasterio.open(path).
            # O with chama a finalização prevista pelo recurso ao sair, mesmo em caso de erro (por exemplo fechar arquivos/respostas).
            with rasterio.open(path) as source:
                # Verifica a condição source.read().sum() == 4; se falsa, o teste falha com AssertionError.
                assert source.read().sum() == 4

        # Executa a verificação local indicada e registra seu resultado no relatório do ambiente.
        check("parquet_pandas_pyarrow_polars", parquet)
        # Executa a verificação local indicada e registra seu resultado no relatório do ambiente.
        check("netcdf_backends", netcdf)
        # Executa a verificação local indicada e registra seu resultado no relatório do ambiente.
        check("grib_eccodes_cfgrib", grib)
        # Executa a verificação local indicada e registra seu resultado no relatório do ambiente.
        check("vector_geopandas_gdal", vector)
        # Executa a verificação local indicada e registra seu resultado no relatório do ambiente.
        check("raster_rasterio_gdal", raster)
    # Define result: o resultado desta operação, que será retornado, impresso ou salvo.
    result = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True)
    # Registra/atualiza o campo 'pip_check' em report['checks']; calcula a expressão à direita antes de atribuir seu resultado.
    report["checks"]["pip_check"] = result.stdout.strip() or result.stderr.strip()
    # Condição: result.returncode.
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if result.returncode:
        # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
        report["errors"].append("pip check failed")
    # Define frozen: a saída de pip freeze com as versões efetivas do ambiente.
    frozen = subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"], capture_output=True, text=True, check=True)
    # Serializa/grava o texto no caminho indicado em UTF-8; write_text substitui o conteúdo existente desse arquivo.
    (ROOT / "requirements-lock-windows.txt").write_text(frozen.stdout, encoding="utf-8")
    # Serializa/grava o texto no caminho indicado em UTF-8; write_text substitui o conteúdo existente desse arquivo.
    (ROOT / "docs/environment.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Devolve o resultado ao chamador: converte para inteiro (True vira 1 e False vira 0).
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return int(bool(report["errors"]))


# PONTO DE ENTRADA — executa o bloco apenas quando este arquivo é iniciado diretamente.
# Ao importar suas funções em outro script/teste, este bloco não roda.
if __name__ == "__main__":
    # Encerra o processo com o código retornado: 0 indica sucesso; valor diferente indica falha ao terminal/agendador.
    raise SystemExit(main())
