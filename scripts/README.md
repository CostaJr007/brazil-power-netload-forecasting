# Python programs

File and function names follow the Portuguese domain vocabulary of the Brazilian power sector (`carga` = load,
`eolica` = wind, `previsao` = forecast, `regua` = benchmark); the tables below explain each one.

## `scripts/`: the pipeline (runs every day)

| File | Role |
|---|---|
| `acquire.py` | Acquisition core: HTTP with retries, hash-addressed Bronze (`Store`), `ROOT`/`DATA_DIR`, catalog CLI and manual download |
| `pipeline.py` | Orchestrates incremental collection (ONS files, load API, MERGE, GFS, ECMWF, INMET, CCEE) → Silver → Gold. `--offline` avoids the network |
| `silver.py` | Bronze → Silver: schema contracts, quarantine and snapshot. **The code of this file defines the Silver version** |
| `basins.py` | Basin polygons: geometry repair, area weights and basin averages |
| `gold.py` | Basin aggregates and DuckDB views (`data/gold/energia.duckdb`) |
| `backfill.py` | History: plans with sizes; with `--execute` downloads and processes with the same code |
| `modelagem.py` | Offline backtest of the inflow and load models (`models/`); results in `docs/inventory/model_results.json` |
| `tabela_modelo.py` | Joins every source into one subsystem × hour table (`docs/tabela_modelo.md`) |
| `baixar_temperatura_prevista.py` / `baixar_vento_sol_previstos.py` | Archived GFS forecasts (Open-Meteo) issued 48 h ahead |
| `carga_d1.py` / `carga_fontes.py` | Backtests of D+1 load and of the value of each data source |
| `baixar_previsao_renovaveis.py` | Archived forecasts (48/72/96 h ahead) of wind and radiation at plant cells |
| `prever_carga_liquida.py` | **Operational forecast** of tomorrow's and the day after's net load, with frozen recipes, current weather and an 80% band |
| `exportar_bi.py` / `gerar_projeto_bi.py` / `relatorio_bi.py` | Star-schema BI tables (`data/bi/`), Power BI semantic model (TMDL) and report pages (PBIR) in `bi/` |
| `gerar_dashboard_html.py` / `dashboard_template.html` | Static HTML dashboard (single file, Plotly) in `docs/dashboard/`, from the same BI tables |
| `auditar_previsoes.py` | Replays the operational forecast over a past week and compares with what happened |
| `carga_liquida_d1.py` | Net load by component vs the ONS DESSEM schedule: D+1 (default) or `--horizonte 2` (see `docs/research/carga_liquida_d1.md` and `carga_liquida_d2.md`) |
| `solar_usinas.py` / `solar_irradiancia.py` | Solar plant ranking, NASA POWER radiation and measured irradiance including curtailment |
| `sazonalidade_carga.py` | D+1 load backtest sliced by season, month, hour band and day type |
| `status_pipeline.py` | Offline status report and alerts (stale report, Task Scheduler code) |
| `discover_weather.py` | Weather directory listing (used by the pipeline) and basin inspection |
| `run_pipeline.ps1` / `install_pipeline_task.ps1` | Wrapper and installer for the Windows Task Scheduler job |

## `scripts/preparacao/`: generated configs and inventories (run only when a source changes)

| File | Role |
|---|---|
| `inventory.py` | ONS catalog → `docs/inventory/ons_catalog.md` and `ons_resources.csv` |
| `build_contracts.py` | Audited schemas → `configs/ons_contracts.json` (review by hand) |
| `plan_weather.py` | Inspects the basin shapefile and builds bounding boxes |
| `download_weather.py` | First weather batch and the INMET station inventory |

## `scripts/diagnostico/`: audits and one-off investigations

| File | Role |
|---|---|
| `audit_endpoints.py` / `summarize_audit.py` | Tests recent dataset URLs and their internal dates |
| `probe_load_api.py` | Original load-API probe (before area codes) |
| `validate_sources.py` / `inspect_samples.py` | The eight initial samples and their coverage |
| `compare_formats.py` | CSV × Parquet of the same file (DuckDB, `EXCEPT ALL`) |
| `inspect_rejections.py` | Reasons for quarantined rows |
| `check_environment.py` | Checks libraries and writes the version lock |
| `report_weather.py` | Report of the first weather batch |
| `residuos_2026.py` | 2026 residuals vs candidate variables, second-stage model and resampling interval (is a new model worth it?) |
| `fuzzy_banda.py` | Fuzzy risk score (heat, ONS bias, holiday): adaptive band and correction weight, selected on 2025 and validated on 2026 |

Scripts in subfolders import modules from `scripts/` (e.g. `from acquire import Store`) through a line that adds the parent folder to `sys.path`.

## Paths

- `ROOT` is the project root. `DATA_DIR` is the data folder: `<project>/data` by default, or the `ENERGY_DATA_DIR` environment variable.
- Manifests store absolute paths. If the data folder moves, `resolve_data_path()` finds files again from `bronze/`, `silver/` and so on.
