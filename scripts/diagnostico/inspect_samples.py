# GUIA DE LEITURA — Mede cobertura temporal e duplicatas das amostras CSV já baixadas.
# Entrada: acquisition_validation.json e caminhos de arquivos nele registrados.
# Saída: sample_coverage.json. As consultas SQL não alteram os dados originais.
# Comentários não executam; a indentação do código define quais instruções pertencem a cada bloco.

"""Read-only coverage inspection of downloaded CSV samples using DuckDB."""
# Importa json: converte entre texto JSON e estruturas Python.
import json
# De pathlib, importa Path: constrói caminhos de arquivos de forma portátil.
from pathlib import Path
# Importa duckdb: consulta CSV/Parquet usando SQL em processo local.
import duckdb

# Define ROOT: a raiz do projeto: parte do caminho deste arquivo, resolve seu endereço absoluto e sobe até a pasta Energy.
ROOT = Path(__file__).resolve().parents[2]


# FUNÇÃO main — coordena a sequência descrita no cabeçalho deste arquivo.
# Recebe parâmetros pelo terminal ou pelos arquivos indicados; os detalhes são explicados nos blocos abaixo.
def main():
    # Define evidence: o documento que acumula evidências das amostras verificadas.
    evidence = json.loads((ROOT / "docs/inventory/acquisition_validation.json").read_text(encoding="utf-8"))
    # Define report: o relatório local que reúne métricas e falhas sem alterar os dados originais.
    report = []
    # Define dates: o mapeamento de campos temporais e suas datas, sem modificar a origem.
    dates = {"balanco-energia-subsistema": "din_instante",
             # Continua o dicionário: define os campos ear-diario-por-subsistema; cada valor vem da expressão após os dois-pontos.
             "ear-diario-por-subsistema": "ear_data",
             # Continua o dicionário: define os campos ena-diario-por-subsistema; cada valor vem da expressão após os dois-pontos.
             "ena-diario-por-subsistema": "ena_data"}
    # Define con: uma conexão DuckDB local para consultas SQL, sem servidor externo.
    con = duckdb.connect()
    # Laço: para cada elemento de evidence['checks'], associa o valor a item e executa o bloco indentado.
    for item in evidence["checks"]:
        # Condição: item['format'] != 'CSV' or item['dataset'] not in dates.
        # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
        if item["format"] != "CSV" or item["dataset"] not in dates:
            # Ignora o restante desta iteração e passa ao próximo item do laço.
            continue
        # Define name: o nome da coluna ou identificador usado nesta iteração.
        name = dates[item["dataset"]]
        # Executa a operação con.read_csv(item['manifest']['path'], delimiter=';', sample_size=-1).create_view('sample', replace=True); seu efeito é descrito pela função ou pelo bloco em que aparece.
        con.read_csv(item["manifest"]["path"], delimiter=";", sample_size=-1).create_view("sample", replace=True)
        # Define result: o resultado desta operação, que será retornado, impresso ou salvo.
        result = con.execute(f'SELECT id_subsistema, count(*), min("{name}"), max("{name}"), count(DISTINCT "{name}") FROM sample GROUP BY 1 ORDER BY 1').fetchall()
        # Define duplicates: a quantidade de repetições ou grupos duplicados, conforme a consulta.
        duplicates = con.execute(f'SELECT count(*) FROM (SELECT id_subsistema,"{name}" FROM sample GROUP BY 1,2 HAVING count(*)>1)').fetchone()[0]
        # Acrescenta este resultado ao fim da lista, preservando os resultados anteriores.
        report.append({"dataset": item["dataset"], "sha256": item["manifest"]["sha256"],
                       # Continua o dicionário: define os campos groups_columns; cada valor vem da expressão após os dois-pontos.
                       "groups_columns": ["id_subsistema", "rows", "min_date", "max_date", "distinct_timestamps"],
                       # Continua o dicionário: define os campos groups, duplicate_key_groups; cada valor vem da expressão após os dois-pontos.
                       "groups": result, "duplicate_key_groups": duplicates,
                       # Continua o dicionário: define os campos note; cada valor vem da expressão após os dois-pontos.
                       "note": "Counts do not establish physical validity or original publication time."})
    # Serializa/grava o texto no caminho indicado em UTF-8; write_text substitui o conteúdo existente desse arquivo.
    (ROOT / "docs/inventory/sample_coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
    print(json.dumps(report, ensure_ascii=False, default=str))


# PONTO DE ENTRADA — executa o bloco apenas quando este arquivo é iniciado diretamente.
# Ao importar suas funções em outro script/teste, este bloco não roda.
if __name__ == "__main__":
    # Executa a operação main(); seu efeito é descrito pela função ou pelo bloco em que aparece.
    main()
