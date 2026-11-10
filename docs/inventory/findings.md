# Resultado da aquisição inicial

Fonte: chamadas reais à API CKAN e downloads HTTP oficiais nesta sessão. Evidência estruturada em acquisition_validation.json, sample_coverage.json e csv_parquet_comparison.json.

## Catálogo

**Escopo: inventário completo dos metadados do catálogo, com validação amostral dos arquivos. Não houve auditoria de acessibilidade dos 15.002 recursos, varredura paginada completa do bucket ou comprovação de atualização/correção de todas as séries.**

- 88 conjuntos resolvidos sem erro pelo package_list + package_show.
- 15.002 recursos catalogados; incluem formatos alternativos, dicionários e recursos potencialmente repetidos.
- 39 conjuntos selecionados para a aquisição do projeto.
- Scraping não foi necessário. Acesso pelo terminal precisou de autorização de rede fora do sandbox; isso é uma característica do ambiente desta sessão, não exigência do ONS.

Consulta posterior à raiz S3 por ListObjectsV2 (max-keys=5): HTTP 200, IsTruncated=true e token de continuação presente. Portanto, abrir a raiz não inventaria o bucket inteiro. A consulta foi apenas um teste de listagem, sem leitura dos objetos retornados; uma auditoria dos dados deve usar o prefixo dataset/ e percorrer todas as páginas. LastModified indica alteração do objeto, não a última data de referência dos registros.

## Amostras

| Amostra | Resultado |
|---|---|
| Balanço 2025 CSV | 43.800 registros; N, NE, S, SE e SIN, 8.760 timestamps distintos em cada grupo |
| Balanço 2025 Parquet | Mesmo schema e mesmos registros do CSV, por EXCEPT ALL nas duas direções com tipos DuckDB |
| EAR 2025 CSV | 1.460 registros; quatro grupos, 365 datas distintas por grupo |
| ENA 2025 CSV | 1.460 registros; quatro grupos, 365 datas distintas por grupo |
| ZIP de bacias | 1.622.722 bytes; CRC verificado; .shp, .shx, .dbf, .prj, .cpg e .qmd presentes |
| Dicionários JSON | Programação diária e carga programada/verificada baixados e decodificados |

As três amostras CSV não apresentaram grupos duplicados na chave proposta (subsistema, referência). Cobertura de 2025 encontrada no balanço: 01/01 00:00 até 31/12 23:00; EAR/ENA: 01/01 até 31/12. Isso não comprova validade física dos valores, latência histórica ou qualidade dos outros anos.

## Dois problemas concretos a considerar na futura Silver

1. **SIN já está no balanço.** Somar todas as linhas de subsistemas sem separar esse agregado pode contar o total novamente.
2. **Chaves com espaços à direita.** EAR e ENA trazem `N ` e `S ` nas amostras, enquanto o balanço tem `N` e `S`. Preservamos os bytes originais; uma regra explícita de normalização será necessária para junções futuras.

## O que permanece sem validação ao vivo

- Dados de observação retornados pela API apicarga (os dicionários foram validados, não a série).
- Equivalência entre API de carga e CSVs de outros produtos.
- Conteúdo/qualidade das demais séries catalogadas.
- Geometrias, CRS e correspondência entre bacias, reservatórios e áreas incrementais; ZIP íntegro não equivale a geometria correta.
- Download de meteorologia e campos disponíveis em cada produto/rodada.
- Planejamento geoespacial GeoPandas e comando de download GFS: código preparado, ainda não validado ao vivo.

Os quatro testes automatizados de aquisição passaram. Os scripts foram compilados com Python 3.13.13. DuckDB instalado no .venv: 1.5.6.
