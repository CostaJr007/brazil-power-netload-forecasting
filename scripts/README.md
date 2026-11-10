# Programas Python

Todos têm comentários em português no próprio código. O [guia de estudo](../docs/guia_de_estudo.md) sugere a ordem de leitura.

## `scripts/`: o pipeline (roda todo dia)

| Arquivo | Papel |
|---|---|
| `acquire.py` | Núcleo de aquisição: HTTP com novas tentativas, Bronze por hash (`Store`), `ROOT`/`DATA_DIR`, CLI de catálogo e download manual |
| `pipeline.py` | Orquestra a coleta incremental (ONS arquivos, API de carga, MERGE, GFS, ECMWF, INMET, CCEE) → Silver → Gold. `--offline` evita rede |
| `silver.py` | Tratamento Bronze → Silver: contratos, quarentena e snapshot. **O código deste arquivo define a versão da Silver** |
| `basins.py` | Polígonos das bacias: reparo de geometria, pesos por área e médias por bacia |
| `gold.py` | Agregados por bacia e views DuckDB (`data/gold/energia.duckdb`) |
| `backfill.py` | Histórico: planeja com tamanhos; com `--execute` baixa e trata usando o mesmo código |
| `status_pipeline.py` | Relatório de situação e alertas (relatório atrasado, código do Agendador), sem rede |
| `discover_weather.py` | Listagem de diretórios meteorológicos (usada pelo pipeline) e inspeção das bacias |
| `run_pipeline.ps1` / `install_pipeline_task.ps1` | Wrapper e instalador da tarefa do Agendador do Windows |

## `scripts/preparacao/`: geraram configurações e inventários (rodar só quando a fonte mudar)

| Arquivo | Papel |
|---|---|
| `inventory.py` | Catálogo ONS → `docs/inventory/ons_catalog.md` e `ons_resources.csv` |
| `build_contracts.py` | Schemas auditados → `configs/ons_contracts.json` (revisar à mão) |
| `plan_weather.py` | Inspeciona o shapefile e gera retângulos por bacia |
| `download_weather.py` | Primeiro lote meteorológico e o inventário de estações INMET |

## `scripts/diagnostico/`: auditorias e investigações pontuais

| Arquivo | Papel |
|---|---|
| `audit_endpoints.py` / `summarize_audit.py` | Testa as URLs recentes dos conjuntos e as datas internas |
| `probe_load_api.py` | Teste original da API de carga (antes dos códigos de área) |
| `validate_sources.py` / `inspect_samples.py` | As oito amostras iniciais e a cobertura delas |
| `compare_formats.py` | CSV × Parquet do mesmo arquivo (DuckDB, `EXCEPT ALL`) |
| `inspect_rejections.py` | Motivos das linhas em quarentena |
| `check_environment.py` | Confere bibliotecas e gera o lock de versões |
| `report_weather.py` | Relatório do primeiro lote meteorológico |

Os scripts das subpastas importam os módulos de `scripts/` (por exemplo `from acquire import Store`) por meio de uma linha que acrescenta a pasta-mãe ao `sys.path`.

## Caminhos

- `ROOT` é a raiz do projeto. `DATA_DIR` é a pasta de dados: o padrão é `<projeto>/data`, ou o valor da variável de ambiente `ENERGY_DATA_DIR`.
- Os manifestos guardam caminhos absolutos. Se a pasta de dados mudar de lugar, `resolve_data_path()` reencontra os arquivos a partir de `bronze/`, `silver/` etc.
