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
| `modelagem.py` | Backtest dos modelos de ENA e carga (`models/`), sem rede; resultado em `docs/inventory/model_results.json` |
| `tabela_modelo.py` | Junta todas as fontes numa tabela subsistema × hora (`docs/tabela_modelo.md`) |
| `baixar_temperatura_prevista.py` / `baixar_vento_sol_previstos.py` | Previsões GFS arquivadas (Open-Meteo), emitidas 48 h antes |
| `carga_d1.py` / `carga_fontes.py` | Backtests da carga de D+1 e do valor de cada fonte de dados |
| `baixar_previsao_renovaveis.py` | Previsões arquivadas (48 h antes) de vento e radiação nas células das usinas |
| `prever_carga_liquida.py` | **Previsão operacional** da carga líquida de amanhã e depois de amanhã, com as receitas congeladas e o tempo previsto atual |
| `exportar_bi.py` / `gerar_projeto_bi.py` | Tabelas do BI em modelo estrela (`data/bi/`) e o projeto Power BI em texto (`bi/`, PBIP + TMDL) |
| `auditar_previsoes.py` | Replay da previsão operacional numa semana passada, contra o que aconteceu |
| `carga_liquida_d1.py` | Carga líquida por peças contra o DESSEM do ONS: D+1 (padrão) ou `--horizonte 2` (ver `docs/research/carga_liquida_d1.md` e `carga_liquida_d2.md`) |
| `solar_usinas.py` / `solar_irradiancia.py` | Ranking das solares, radiação (NASA POWER) e irradiância medida com efeito dos cortes |
| `sazonalidade_carga.py` | Backtest da carga de D+1 fatiado por estação, mês, faixa horária e tipo de dia |
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
| `residuos_2026.py` | Resíduos de 2026 × variáveis candidatas, segundo estágio e intervalo por reamostragem (vale a pena remodelar?) |
| `fuzzy_banda.py` | Risco fuzzy (calor, viés do ONS, feriado): banda de previsão adaptativa e peso da correção, escolha 2025 × confirmação 2026 |

Os scripts das subpastas importam os módulos de `scripts/` (por exemplo `from acquire import Store`) por meio de uma linha que acrescenta a pasta-mãe ao `sys.path`.

## Caminhos

- `ROOT` é a raiz do projeto. `DATA_DIR` é a pasta de dados: o padrão é `<projeto>/data`, ou o valor da variável de ambiente `ENERGY_DATA_DIR`.
- Os manifestos guardam caminhos absolutos. Se a pasta de dados mudar de lugar, `resolve_data_path()` reencontra os arquivos a partir de `bronze/`, `silver/` etc.
