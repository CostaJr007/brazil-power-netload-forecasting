# GUIA DE LEITURA — Compara os registros de um CSV e um Parquet locais, incluindo a quantidade de repetições.
# Entrada: caminhos dos dois arquivos no terminal. Saída: resultado na tela e JSON opcional.
# Não baixa arquivos: a equivalência vale sob os tipos e as conversões adotados pelo DuckDB.
# Comentários não executam; a indentação do código define quais instruções pertencem a cada bloco.

"""Optional DuckDB check: compare logical CSV/Parquet records, retaining duplicates.

Pass --decimal , if the SOURCE dictionary specifies comma decimals.
This is not an API-versus-CSV equivalence claim.
"""
# Importa argparse: interpreta opções do terminal, como --dataset e --execute.
import argparse
# Importa json: converte entre texto JSON e estruturas Python.
import json
# De pathlib, importa Path: constrói caminhos de arquivos de forma portátil.
from pathlib import Path


# FUNÇÃO main — coordena a sequência descrita no cabeçalho deste arquivo.
# Recebe parâmetros pelo terminal ou pelos arquivos indicados; os detalhes são explicados nos blocos abaixo.
def main():
    # Importa duckdb: consulta CSV/Parquet usando SQL em processo local.
    import duckdb

    # Define parser: o interpretador dos argumentos da linha de comando.
    parser = argparse.ArgumentParser(description=__doc__)
    # Configura 'csv': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    parser.add_argument("csv")
    # Configura 'parquet': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    parser.add_argument("parquet")
    # Configura '--decimal': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    parser.add_argument("--decimal", default=".", choices=[".", ","])
    # Configura '--output': type converte a entrada; default define o padrão; required exige o valor; action controla flags/listas.
    parser.add_argument("--output", type=Path)
    # Define args: as opções do terminal já interpretadas, acessíveis como args.dataset etc..
    args = parser.parse_args()
    # Define con: uma conexão DuckDB local para consultas SQL, sem servidor externo.
    con = duckdb.connect()
    # Executa a operação con.read_csv(args.csv, delimiter=';', decimal=args.decimal, sample_size=-1).create_view('csv_data'); seu efeito é descrito pela função ou pelo bloco em que aparece.
    con.read_csv(args.csv, delimiter=";", decimal=args.decimal, sample_size=-1).create_view("csv_data")
    # Executa a operação con.read_parquet(args.parquet).create_view('parquet_data'); seu efeito é descrito pela função ou pelo bloco em que aparece.
    con.read_parquet(args.parquet).create_view("parquet_data")
    # Define csv_cols: os nomes das colunas do CSV, na ordem de leitura.
    csv_cols = [r[0] for r in con.execute("DESCRIBE csv_data").fetchall()]
    # Define pq_cols: os nomes das colunas do Parquet para verificar equivalência de schema.
    pq_cols = [r[0] for r in con.execute("DESCRIBE parquet_data").fetchall()]
    # Condição: set(csv_cols) != set(pq_cols).
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if set(csv_cols) != set(pq_cols):
        # Interrompe o fluxo normal com ValueError(f'Different columns: CSV={csv_cols}, Parquet={pq_cols}'); o bloco except apropriado poderá tratar a falha.
        raise ValueError(f"Different columns: CSV={csv_cols}, Parquet={pq_cols}")
    # Define cols: a lista SQL de colunas protegidas por aspas e na mesma ordem nos dois formatos.
    cols = ",".join('"' + c.replace('"', '""') + '"' for c in csv_cols)
    # DuckDB chooses compatible types; inspect inferred schemas before interpreting.
    # Define delta_a: a contagem de linhas presentes apenas no CSV, preservando repetições via EXCEPT ALL.
    delta_a = con.execute(f"SELECT count(*) FROM ((SELECT {cols} FROM csv_data) EXCEPT ALL (SELECT {cols} FROM parquet_data))").fetchone()[0]
    # Define delta_b: a contagem de linhas presentes apenas no Parquet, verificando a outra direção.
    delta_b = con.execute(f"SELECT count(*) FROM ((SELECT {cols} FROM parquet_data) EXCEPT ALL (SELECT {cols} FROM csv_data))").fetchone()[0]
    # Define result: o resultado desta operação, que será retornado, impresso ou salvo.
    result = {"csv_only_rows": delta_a, "parquet_only_rows": delta_b,
                      # Continua o dicionário: define os campos equal_under_duckdb_type_coercion; cada valor vem da expressão após os dois-pontos.
                      "equal_under_duckdb_type_coercion": delta_a == delta_b == 0,
                      # Continua o dicionário: define os campos csv_schema; cada valor vem da expressão após os dois-pontos.
                      "csv_schema": con.execute("DESCRIBE csv_data").fetchall(),
                      # Continua o dicionário: define os campos parquet_schema; cada valor vem da expressão após os dois-pontos.
                      "parquet_schema": con.execute("DESCRIBE parquet_data").fetchall()}
    # Condição: args.output.
    # Se for verdadeira, executa o bloco indentado; se falsa, procura elif/else ou continua após o bloco.
    if args.output:
        # Garante a existência da pasta; parents=True cria pais ausentes e exist_ok=True aceita uma pasta já existente.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Serializa/grava o texto no caminho indicado em UTF-8; write_text substitui o conteúdo existente desse arquivo.
        args.output.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    # Mostra o resultado/progresso no terminal; imprimir não significa salvar um arquivo.
    print(json.dumps(result, default=str))
    # Devolve o resultado ao chamador: converte para inteiro (True vira 1 e False vira 0).
    # Depois de return, o restante desta função não é executado (mas um finally pendente ainda roda).
    return int(bool(delta_a or delta_b))


# PONTO DE ENTRADA — executa o bloco apenas quando este arquivo é iniciado diretamente.
# Ao importar suas funções em outro script/teste, este bloco não roda.
if __name__ == "__main__":
    # Encerra o processo com o código retornado: 0 indica sucesso; valor diferente indica falha ao terminal/agendador.
    raise SystemExit(main())
