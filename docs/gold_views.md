# Gold layer and views (DuckDB)

`scripts/gold.py` rebuilds `data/gold/energia.duckdb` whenever new Silver data arrives. The database contains
**views only**, no data copies: they read the current Silver and Gold Parquet files. View and column names follow the
Portuguese vocabulary of the source data (`carga` = load, `eolica` = wind, `chuva` = rain, `bacia` = basin).

```powershell
.\.venv\Scripts\python.exe scripts/gold.py      # manual refresh
.\.venv\Scripts\python.exe -c "import duckdb; c=duckdb.connect('data/gold/energia.duckdb', read_only=True); print(c.sql('SHOW TABLES'))"
```

Open the file **read-only** in an IDE. A write connection prevents the pipeline from replacing the database; in that
case the run logs a `gold` error and continues.

## Base views

| View | Content |
|---|---|
| `silver_<dataset>` | The current `.valid.parquet` files of each Silver dataset (e.g. `silver_ena_diario_por_bacia`) |
| `gold_basin_weather` | Basin average of each weather snapshot (MERGE, GFS, ECMWF): `value`, `coverage`, intervals and run |
| `basins` | 31 basins: area in km² and whether the geometry was repaired |
| `basin_ena_mapping` | Polygon ↔ ENA `nom_bacia` and the type of match |

## Business views

| View | Grain | Use |
|---|---|---|
| `vw_chuva_observada_bacia_diaria` | basin × day | MERGE rain per basin, area-weighted, with `cobertura_area` |
| `vw_previsao_chuva_bacia` | model × basin × run × lead | Forecast rain per period (difference of accumulations), ECMWF and GFS |
| `vw_ena_bacia_diaria` | ONS basin × day | Gross inflow (average MW and % of long-term mean) and storable inflow |
| `vw_chuva_x_ena_bacia` | basin × day | **Hypothesis table:** observed rain × inflow |
| `vw_carga_prevista_vs_verificada` | subsystem × half hour (UTC) | ONS forecast × actual, distributed generation and forecast error |
| `vw_balanco_carga_liquida` | subsystem × hour | Load, wind, solar, hydro, thermal and net load (no national aggregate) |
| `vw_ear_subsistema_diaria` | subsystem × day | Reservoir storage in % and MW-month |
| `vw_cmo_semanal` | subsystem × week | Mean and per-block marginal cost |
| `vw_painel_energia_diario` | day (national) | **Monitoring panel:** balance, net-load ramp, inflow, storage, curtailment, CMO and estimated price |
| `vw_frescor_fontes` | source | Latest published date of each source, days of delay and last collection (negative = future data already published, e.g. schedules and CMO) |
| `vw_balanco_diario` / `vw_balanco_horario_sin` | subsystem and national × day / national × hour | Load, wind, solar, hydro, thermal and net load |
| `vw_renovaveis_diario` | source × subsystem × state × day | Wind and solar: generation, capacity and capacity factor |
| `vw_cortes_renovaveis_diario` | source × subsystem × day | Curtailed generation by reason (energy, reliability, electrical) and % of potential |
| `vw_hidro_subsistema_diaria` | subsystem and national × day | Inflow and storage; national percentages weighted |
| `vw_ena_bacia_sem_dupla_contagem` | basin × day | Basin inflow that is safe to sum |
| `vw_conferencia_soma_bacias` | day | Sum of basins vs national inflow; the difference should be ~0 |
| `vw_ree_diaria` | REE × day | Inflow and storage per equivalent reservoir |
| `vw_pld_estimado_horario` | subsystem × hour (2021+) | **Estimated** spot price: ONS CMO clipped to the regulator's floor and hourly cap (`origem` = `cmo`, `piso` or `teto_horario`) |
| `vw_pld_estimado_diario` | subsystem × day (2021+) | Daily mean of the estimate, clipped to the structural cap |

## Rules and caveats

- **Time zone:** only the load API (`*_utc`) and weather data declare UTC. The `instante_fonte` and `data_referencia` columns of ONS files stay as published.
- **Basin average:** `Σ(value × cell area inside the basin) / Σ(area with value)`, areas in EPSG:5880. Missing cells never become zero, and `cobertura_area < 1` flags missing data.
- **Rain forecasts:** ECMWF and GFS accumulate from the start of the run; `chuva_periodo_mm` is the difference between consecutive leads (`periodo_h` gives the period length).
- **Backtesting:** the views pick the **latest** version of each value. To simulate "what was known that day", filter Silver by `_available_at_utc` and use the forecast run (`rodada_utc`), never observed rain in place of forecast rain.
- **Summing basins:** do not sum `vw_ena_bacia_diaria` directly. In 2026 it carries an `AMAZONAS` row together with its sub-basins and the total comes out up to 34% above the national value; use `vw_ena_bacia_sem_dupla_contagem`.
- **Source cadence:** each dataset is published on its own schedule. `fontes_ausentes` in the panel lists what was missing that day, and `scripts/horarios_publicacao.py` measures real publication times from Bronze. Old gaps are expected: CMO starts in 2020 and curtailment in Oct 2021.
- **Solar in the balance vs plants:** the balance's `solar_mwmed` is much larger than the sum in `vw_renovaveis_diario` because it includes rooftop generation. Plants + distributed generation reproduce the balance with 0.96–0.97 correlation in 2024–2025, 500–1,500 average MW above it.
- **Curtailment:** `corte_mwmed` uses the unrealised generation computed by ONS, with history from Oct 2021 (wind) and Apr 2024 (solar).
- **Estimated price:** not the official CCEE price, which is blocked from this network. CCEE runs its own DESSEM, so the value can differ even inside the limits. Limits and sources in `configs/pld_limits.json`.
- A view depending on a missing dataset is skipped and logged in `docs/inventory/gold_status.json`.
