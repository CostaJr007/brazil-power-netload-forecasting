# GUIA DE LEITURA — Inspeciona polígonos reais e prepara retângulos para pedidos meteorológicos.
# Entrada: caminho geográfico e coluna identificadora, informados no terminal.
# Saída: weather_extents.json quando --id-column é informado; não baixa meteorologia nem calcula chuva média.
# Comentários não executam; a indentação do código define quais instruções pertencem a cada bloco.

"""Prepare rectangular weather download extents from real basin geometries.

Optional spatial dependencies required. This does not compute basin averages.
"""
# Importa argparse: interpreta opções do terminal, como --dataset e --execute.
import argparse
# Importa json: converte entre texto JSON e estruturas Python.
import json
# De pathlib, importa Path: constrói caminhos de arquivos de forma portátil.
from pathlib import Path

# DATA_DIR: pasta de dados configurável (ENERGY_DATA_DIR), definida no coletor central.
# Scripts desta subpasta reutilizam os módulos de scripts/ (acquire, pipeline...).
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from acquire import DATA_DIR


# FUNÇÃO main — coordena a sequência descrita no cabeçalho deste arquivo.
# Recebe parâmetros pelo terminal ou pelos arquivos indicados; os detalhes são explicados nos blocos abaixo.
def main():
    # Importa geopandas: lê geometrias e trabalha com sistemas de coordenadas.
    import geopandas as gpd

    # Define parser: o interpretador dos argumentos da linha de comando.
    parser = argparse.ArgumentParser(description=__doc__)
    # Configura 'polygons': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    parser.add_argument("polygons", help="Shapefile, GPKG or zip://ABSOLUTE_PATH_TO_ZIP")
    # Configura '--id-column': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    parser.add_argument("--id-column", help="Omit to inspect columns, CRS and bounds only")
    # Configura '--output': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    parser.add_argument("--output", type=Path, default=DATA_DIR / "geography/weather_extents.json")
    # Define args: as opções do terminal já interpretadas, acessíveis como args.dataset etc..
    args = parser.parse_args()
    # Define frame: a tabela geográfica que inclui atributos, geometrias e CRS.
    frame = gpd.read_file(args.polygons)
    # Condição: frame.crs is None.
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if frame.crs is None:
        # Interrompe o fluxo normal com ValueError('Source CRS absent; do not assume EPSG:4326'); o bloco except apropriado poderá tratar a falha.
        raise ValueError("Source CRS absent; do not assume EPSG:4326")
    # Condição: frame.empty or frame.geometry.isna().any() or frame.geometry.is_empty.any() or (not frame.geometry.is_valid.all()).
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if frame.empty or frame.geometry.isna().any() or frame.geometry.is_empty.any() or not frame.geometry.is_valid.all():
        # Interrompe o fluxo normal com ValueError('Empty, missing or invalid source geometries; inspect before planning'); o bloco except apropriado poderá tratar a falha.
        raise ValueError("Empty, missing or invalid source geometries; inspect before planning")
    # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
    print(json.dumps({"columns": list(frame.columns), "source_crs": str(frame.crs),
                      # Continua o dicionário: define os campos features; cada valor vem da expressão após os dois-pontos.
                      "features": len(frame)}, ensure_ascii=False))
    # Condição: not args.id_column.
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if not args.id_column:
        # Encerra esta função sem valor explícito (Python retorna None).
        return
    # Condição: args.id_column not in frame.columns.
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if args.id_column not in frame.columns:
        # Interrompe o fluxo normal com ValueError('ID column not found; inspect printed columns'); o bloco except apropriado poderá tratar a falha.
        raise ValueError("ID column not found; inspect printed columns")
    # Condição: frame[args.id_column].isna().any() or frame[args.id_column].duplicated().any().
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if frame[args.id_column].isna().any() or frame[args.id_column].duplicated().any():
        # Interrompe o fluxo normal com ValueError('Basin IDs must be present and unique'); o bloco except apropriado poderá tratar a falha.
        raise ValueError("Basin IDs must be present and unique")
    # Define wgs84: uma cópia geográfica convertida para longitude/latitude em EPSG:4326.
    wgs84 = frame.to_crs("EPSG:4326")
    # Define output: o objeto/caminho de saída ou arquivo aberto para escrita, conforme este bloco.
    output = {"source": args.polygons, "source_crs": str(frame.crs),
              # Continua o dicionário: define os campos bbox_order, regions; cada valor vem da expressão após os dois-pontos.
              "bbox_order": "west,south,east,north", "regions": [
                  {"id": str(row[args.id_column]), "bbox": list(row.geometry.bounds)}
                  # Continua a expressão anterior: aplica a iteração ou a condição adicional indicada nesta linha.
                  for _, row in wgs84.iterrows()],
              # Continua o dicionário: define os campos note; cada valor vem da expressão após os dois-pontos.
              "note": "Rectangles include cells outside the basin. Polygon intersection and area weights remain a separate step."}
    # Garante a existência da pasta; parents=True cria pais ausentes e exist_ok=True aceita uma pasta já existente.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Serializa/grava o texto no caminho indicado em UTF-8; write_text substitui o conteúdo existente desse arquivo.
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


# PONTO DE ENTRADA — executa o bloco apenas quando este arquivo é iniciado diretamente.
# Ao importar suas funções em outro script/teste, este bloco não roda.
if __name__ == "__main__":
    # Executa a operação main(); seu efeito é descrito pela função ou pelo bloco em que aparece.
    main()
