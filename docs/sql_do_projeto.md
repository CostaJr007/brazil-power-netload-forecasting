# Como ler o SQL que aparece nos scripts

Este documento explica as instruções SQL sem inserir comentários dentro dos textos enviados ao banco. Os comentários Python mantêm a lógica e os bytes dos dados inalterados.

## SQLite: histórico de aquisição

`CREATE TABLE IF NOT EXISTS attempts` cria uma tabela apenas na primeira execução. Seus campos:

| Campo | Tipo | Significado |
|---|---|---|
| attempt_id | TEXT PRIMARY KEY | Identificador único da tentativa |
| started_at / completed_at | TEXT | Instantes registrados em ISO 8601 |
| source / dataset / resource_id | TEXT | Origem e recurso tentados |
| url | TEXT | Endereço consultado |
| status | TEXT | started, downloaded, unchanged ou error |
| sha256 | TEXT | Assinatura do conteúdo recebido |
| bytes | INTEGER | Quantidade de bytes recebidos |
| path | TEXT | Arquivo local associado |
| detail | TEXT | Mensagem de erro quando ocorreu |

`INSERT` registra uma tentativa nova; `UPDATE` conclui a mesma tentativa. O `WHERE attempt_id=?` delimita a linha. A chamada `execute(sql, tupla)` associa os valores aos `?`, evitando montar o SQL com os valores diretamente.

## DuckDB: inspecionar arquivos

`read_csv(...).create_view("sample")` ou `read_parquet(...).create_view(...)` expõe os registros sob um nome SQL. Isso não reescreve os arquivos originais.

- `DESCRIBE sample`: lista nome e tipo de cada coluna.
- `SELECT count(*) FROM sample`: conta linhas, inclusive as que têm campos nulos.
- `count(coluna)`: conta valores não nulos daquela coluna.
- `count(DISTINCT coluna)`: conta valores distintos não nulos.
- `min` e `max`: menor e maior valor interpretado.
- `GROUP BY 1`: agrupa pela primeira expressão do SELECT. É uma forma abreviada de nomear a coluna.
- `ORDER BY 1`: ordena pela primeira expressão do SELECT.
- `HAVING count(*) > 1`: após agrupar, mantém chaves com mais de uma linha.

Em `SELECT count(*) FROM (SELECT chave ... GROUP BY chave HAVING count(*)>1)`, a consulta interna identifica os grupos duplicados; a externa conta quantos grupos existem. Isso é diferente de contar todas as linhas extras.

## Interpretar datas sem abortar a auditoria

`try_cast(campo AS TIMESTAMP)` tenta converter o campo e devolve NULL se não conseguir. `try_strptime` tenta formatos explícitos, como `%Y%m%d` (20261110). `coalesce(a,b)` escolhe o primeiro valor não nulo.

Essa conversão existe na consulta de inspeção. O arquivo original não é limpo nem atualizado. Se uma coluna contém formatos não reconhecidos, a quantidade de valores interpretados pode ser menor que o total de linhas; por isso o relatório registra contagens.

Datas de entrada em operação, fim de vigência e data observada não são intercambiáveis. É por isso que a consolidação trata cadastros separadamente.

## Comparar formatos

`A EXCEPT ALL B` devolve as linhas de A que não encontram correspondência suficiente em B. O ALL preserva repetições.

Exemplo: A tem `[x,x,y]` e B tem `[x,y]`. A - B contém um x; sem ALL a repetição poderia desaparecer. Para comparar, fazemos também B - A. Ambas as diferenças devem ter zero linhas.

Os nomes de colunas são protegidos com aspas duplas. Se um nome contém aspas, elas são duplicadas. Isso é proteção de **identificadores SQL**; não é a mesma coisa que placeholders para valores.

O DuckDB pode escolher tipos compatíveis entre as tabelas. O resultado vale sob essas conversões; o relatório inclui os schemas para interpretação.
