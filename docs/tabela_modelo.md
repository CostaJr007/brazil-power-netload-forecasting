# Single modeling table

`scripts/tabela_modelo.py` joins the sources into `data/gold/tabela_modelo.parquet` (and `.csv`): **one row per subsystem × local hour (UTC−3)**. A new model only needs to read this file.

Each column holds the value for its own timestamp. The last column below says when the value becomes available: to forecast day T on the day before, apply the indicated lag.

| Columns | Source | When it is known |
|---|---|---|
| `carga` | ONS, verified load | Assumed T+2 (2-day lag) |
| `programada` | ONS, scheduled load | Day before (T−1); exact publication time not confirmed |
| `temp_prev_48h`, `radiacao_prev`, `vento_prev`, `umidade_prev`, `nuvens_prev` | GFS via Open-Meteo, mean of the subsystem's state capitals | Forecast issued 48 h ahead; usable without lag. The last four only exist since Feb/2024 |
| `temp_analise` | Open-Meteo, analysis | Only after the fact: use only to measure the perfect-forecast bound |
| `temp`, `temp_max`, `radiacao`, `vento`, `umidade`, `chuva` | INMET, stations in the 3 highest-load states (daily) | 2-day lag in the backtest; INMET's yearly package is published with a longer delay |
| `ear`, `ena_pct` | ONS (daily) | 2-day lag |
| `eolica`, `solar`, `hidraulica`, `termica` | ONS, balance per subsystem (daily mean) | 2-day lag |
| `dia_semana`, `mes`, `feriado`, `vespera`, `pos_feriado`, `ponte` | Calendar | Known in advance |

Rain and ENA **per basin** stay in `vw_chuva_x_ena_bacia`, because the grain is different (basin × day).
