# Next-day (D+1) hourly load forecast

Run of 2026-11-10. Yearly walk-forward test from 2023 to 2026-11-08 on the 4 subsystems. Full numbers in
`docs/inventory/carga_d1_results.json` and `carga_fontes_results.json`; code in `models/carga_d1.py` and
`models/carga_fontes.py`.

Information used to forecast day T: verified load up to T−2 and temperature forecast 48 h before each hour
(archived GFS, Open-Meteo). The forecast can therefore be issued before ONS publishes its scheduled load.

## How much each source helps (mean hourly error, MAPE)

| Variables added to load history and calendar | Forecasting verified load | Forecasting the ONS schedule |
|---|---|---|
| History and calendar only | 3.05% | 2.10% |
| + forecast temperature | **2.63%** | **1.99%** |
| + observed weather (sun, wind, humidity, rain) | 2.83% | 2.01% |
| + reservoirs (EAR, ENA) | 3.03% (no significant effect) | 2.11% (no effect) |
| + plant generation | 3.05% (no effect) | 2.10% (no effect) |
| Everything, Ridge | **2.58%** | **1.97%** |
| Everything, gradient boosting | 2.75% | 2.16% |

Reference: the ONS scheduled load errs 3.09% against verified load over the same period.

- **Forecast temperature is the decisive variable.** In SE/CO the error falls from 3.16% to 2.22%.
- **Reservoirs and generation do not explain load,** which makes physical sense: consumption depends on weather and calendar, not on how much water is in the reservoirs. These data matter for price, not for load.
- **Best model: one Ridge per hour of the day.** It beat gradient boosting on both targets.
- **Blend with ONS:** the mean of corrected ONS, Ridge and boosting was best in 2023 and 2024 and confirmed in 2025 and 2026 (MAE 12.5% below ONS and 4.7% below the bias rule, 95% CI excluding zero).

## Limits

- Forecast wind, radiation and humidity were not tested for load (Open-Meteo returned persistent 503 errors at the time). The ONS error rises from ~2.2% overnight to ~4.6% at midday, consistent with rooftop solar, a hypothesis later used in the net-load model.
- INMET observed weather comes in yearly packages published with delay; production would need a daily source.
- Temperature is the simple mean of 3–4 capitals per subsystem, not load-weighted.
- "Everything" was evaluated over the whole period, without a separate confirmation slice.
- The scheduled load is assumed to be the one published the day before; the exact publication time was not confirmed.
- **Revisions:** ONS rewrites verified load after the first release (`din_atualizacao` can be more than a year after the day). The backtest uses the final value, so the real-time error may be slightly larger. The 2-day lag matches what was observed on the evening of 2026-11-10, when the latest verified day was 11-09.

## Next step: price

Forecast CMO or estimated PLD in two stages: first the regime (floor, normal or cap), then the level by quantiles,
with storage, inflow, forecast net load and the D+1 load error as inputs.

Sources: [hourly linear models for D+1 forecasting](https://ir.cwi.nl/pub/28449/28449.pdf) · [Ridge, Lasso and neural network comparison in GEFCom2014](https://10wvvw.easychair.org/publications/preprint/Jcdq/open) · [Open-Meteo Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api)
