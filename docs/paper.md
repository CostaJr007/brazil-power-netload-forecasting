# Beating the grid operator's net-load schedule with open data: a leakage-safe forecasting pipeline for the Brazilian power system

*Technical report · November 2026 · personal research project*

## Abstract

Brazil's short-term electricity price is set by the grid operator's (ONS) day-ahead dispatch model, which
balances **net load** (load minus wind and solar) against hydro, thermal and interchange. We ask whether a
fully open-data pipeline can forecast hourly net load better than the free public references a trading desk
already has. We build a Bronze/Silver/Gold data platform over 37 ONS datasets, the ONS load API and five
weather sources. Each component (load, wind, solar) is forecast per subsystem with per-hour Ridge
regressions, gradient boosting and bias-corrected operator schedules. Combination "recipes" are selected on
2025 and validated on 2026 in a walk-forward design that only uses information available at 10 pm the day
before. For the national grid in 2026, the model reduces hourly net-load MAE by **11.2%** against the
operator's day-ahead schedule at D+1 (2,104 vs 2,371 MW), and by **25.9%** at D+2, before any official
schedule exists, against a bias-corrected previous-day schedule (2,594 vs 3,501 MW). Archived weather
forecasts are the main source of skill, cutting error by 37% (wind), 22% (solar) and 17% (load). An empirical
80% prediction band is well calibrated (79–80% coverage). We also report what did **not** work: extra heat
features, a second-stage residual model and fuzzy-logic risk bands all failed out of sample. A one-week live
replay shows the method's main weakness: the operator's bias can flip sign during heat waves.

## 1. Introduction

Net load is the quantity that hydro and thermal plants must cover after wind and solar. In Brazil it drives
the marginal cost of operation (CMO) and therefore the spot price (PLD). The operator publishes its own
forecast inside the day-ahead schedule (DESSEM), so the relevant question for a trader is not "can we forecast
net load?" but **"can we forecast it better than the operator, or earlier?"**

This report documents a project that answers that question with three constraints:

1. **Open data only:** ONS open data and APIs, public weather models and archived forecasts.
2. **No look-ahead:** every input is restricted to what was published at decision time, verified by tests.
3. **A fair benchmark:** each model is scored against the strongest free reference, not against a naive one.

## 2. Data

### 2.1 Sources

| Source | Variables | Use |
|---|---|---|
| ONS open data (CKAN), 37 datasets | Hourly energy balance by subsystem (load, wind, solar, hydro, thermal), DESSEM schedule, reservoir storage and inflow by basin, CMO, curtailment | Targets, benchmarks, context |
| ONS load API | Scheduled and verified load, including distributed generation, UTC | Load model and its benchmark |
| Open-Meteo Previous Runs | Forecasts **as issued** 48, 72 and 96 h ahead (GFS and ECMWF): 100 m wind, shortwave radiation, cloud cover, 2 m temperature | Model features, no hindsight |
| Open-Meteo forecast API | Live forecasts at the same points | Operational forecast |
| MERGE/CPTEC, ECMWF Open Data, GFS, INMET | Observed rain, gridded forecasts, station observations | Inflow models, placebo tests |

The study period for net load runs from 2025-05-23, when the public DESSEM schedule begins, to 2026-11-07.
The four subsystems are Southeast/Center-West (SE), South (S), Northeast (NE) and North (N); the national
grid (SIN) is their sum.

### 2.2 Platform

Raw bytes land in a **Bronze** layer addressed by SHA-256, with every revision preserved and every download
attempt logged. A **Silver** layer applies a schema contract per dataset: types, normalised keys, quarantine of
invalid rows (never silently fixed), lineage to the source file and a transformation version. A **Gold** layer
exposes business views in DuckDB without copying data. Weather grids are averaged over 31 hydro-basin polygons
with exact cell-area weights in an equal-area projection (EPSG:5880).

### 2.3 Cleaning

Applied before any model, each rule motivated by an observed defect:

- Solar above 50 MW between 8 pm and 4 am local time is set to missing.
- Wind or solar values identical for at least 4 consecutive hours above 50 MW ("frozen" telemetry) are set to missing.
- Load at or below zero is set to missing.
- DESSEM hours are kept only when both half-hours were published (136 subsystem-days were half-published).
- The most recent day of the balance is preliminary and excluded from backtests.

Fewer than 1% of hours are affected.

### 2.4 Weather features

Plants are grouped into 1° cells weighted by installed capacity, keeping up to 15 cells per source and
subsystem. Temperature is taken at the main capital cities of each subsystem. Physically impossible model
outputs (negative radiation, cloud cover outside 0–100%) are clipped. For each variable the model receives the
forecast value, its anomaly against the mean of the previous 28 forecasts for the same hour, and the squared
anomaly. For load, temperature enters as an anomaly against the previous 30 days, its square, and cooling and
heating degrees (above 24 °C and below 18 °C).

## 3. Methodology

### 3.1 Decision timing

The forecast is issued at **10 pm Brasília time on day D**. At that moment:

| Horizon | Verified data known up to | Operator schedule available | Weather run used |
|---|---|---|---|
| D+1 | D−1 (gap of 2 days) | DESSEM for D+1 (published 3–5 pm) | issued 48 h before the target |
| D+2 | D−1 (gap of 3 days) | DESSEM for D+1 only, i.e. the previous day's schedule | issued 72 h before the target |

Every lag in the feature set is computed as `max(nominal lag, gap)`. Unit tests overwrite the future
with extreme values and check that the forecast does not change.

### 3.2 Targets and models

Each component is modelled separately per subsystem, and net load is assembled as load − wind − solar.

- **Ratio targets:** load is modelled as `log(load / level)` and renewables as `output / level`, capped at 3, where *level* is the 28-day mean of the same hour known at decision time. This removes trend and installed-capacity growth (and absorbs curtailment), so the model learns deviations.
- **Features:** recent ratios (2, 7 and 14 days), a 7-day trend, operator error lags (2, 3, 7, 14 days and 7/28-day means), weather features (§2.4), and a calendar with national holidays, eves, days after, bridge days and weekday dummies.
- **Ridge per hour:** standardised features, α = 10, one model per hour of the day.
- **Gradient boosting** (scikit-learn HistGradientBoosting): 300 iterations, learning rate 0.05, 31 leaves, min. 40 samples per leaf, L2 = 1, pooled across hours.
- **Operator references:** the DESSEM value (`ons`); the same value corrected by the 28-day mean error at the same hour (`ons_corrected`); for D+2, the previous day's schedule corrected by the mean error of the last four same-weekday, same-hour occurrences (`ons_prev_weekday`).
- **Recipes:** 50/50 blends of the ML mean with each operator reference, plus the pure models. One recipe is chosen **per component and horizon on 2025 only**.

Models are refit every quarter on all data before the quarter, because archived weather forecasts only start in 2024.

### 3.3 Benchmarks and inference

- **D+1 benchmark:** the operator's DESSEM schedule. We also report the gain over the bias-corrected schedule, a stronger reference.
- **D+2 benchmark:** the previous-day schedule corrected by hour and weekday. A naive version made the first D+2 result look like a 42% gain; the weekday correction brought it down to 26%. That gap is why benchmark choice is treated as part of the method.
- **Uncertainty:** differences in MAE are given with 95% confidence intervals from a **14-day block bootstrap**, which preserves the autocorrelation of forecast errors.

### 3.4 Prediction band

For each subsystem and hour, the 10th and 90th percentiles of the model's errors over the previous 120 days,
excluding the day before decision, define an 80% band. This is the limit of a Monte Carlo resampling of past
errors. It is recomputed monthly in the backtest and at every decision in operations.

### 3.5 Recipes selected on 2025

| Horizon | Load | Wind | Solar |
|---|---|---|---|
| D+1 | ML + corrected ONS (50/50) | ML + corrected ONS (50/50) | corrected ONS |
| D+2 | Ridge + GBM mean | GBM | ML + weekday-corrected T−1 schedule |

At D+1 the operator's own schedule is hard to beat alone, so the model works best blended with it. At D+2
the operator has not yet seen the weather for the target day, and pure ML wins for load and wind.

## 4. Results

### 4.1 Net load, national grid, validation year 2026

| Horizon | Model MAE | Benchmark MAE | Reduction | Additional evidence |
|---|---|---|---|---|
| D+1 | 2,104 MW | 2,371 MW (DESSEM) | **11.2%** | −94 MW vs bias-corrected DESSEM, 95% CI [−171, −19] |
| D+2 | 2,594 MW | 3,501 MW (weekday-corrected T−1) | **25.9%** | 95% CI of the difference [−1,195, −580] MW; anticipates the not-yet-published DESSEM with MAE 2,256 vs 3,021 MW |

The model beats the benchmark on 64% of days at D+1 and 69% at D+2. Errors peak in the late morning
(11 am at D+1), when solar ramps and solar forecast errors are largest, not at the evening load peak.
Holidays and weekends are harder than weekdays (D+1: 2,333 and 2,250 vs 2,041 MW), but the model still beats
the benchmark on both.

### 4.2 Value of each information source (2026, D+1)

| Component | MAE without weather | MAE with weather | Reduction |
|---|---|---|---|
| Wind | 703 MW | 446 MW | 37% |
| Solar | 406 MW | 316 MW | 22% |
| Load | 682 MW | 569 MW | 17% |

Reservoir storage, inflows and past generation added nothing to load forecasts. Station temperature (INMET)
helps on its own but adds nothing once forecast temperature is present. In a placebo test, replacing observed
rain with shuffled rain reduced 1-day inflow skill from 30.5% to 23.4%, confirming the rain signal is real.

### 4.3 Other models in the pipeline

| Forecast | Benchmark | Result |
|---|---|---|
| Load D+1 by subsystem | ONS scheduled load (API) | −22% MAE nationally; −26 MW/h beyond bias correction |
| Basin inflow (ENA), 1/3/7/14 days | Persistence | 30.5%, 19.2%, 14.1%, 14.9% skill |

### 4.4 Calibration

The 80% band covered **79.2%** of hours at D+1 and **79.5%** at D+2 in 2026. Its average width is about
6.4 GW at D+1 and 8.1 GW at D+2 for the national grid.

## 5. What did not work

Before retraining with new variables, we checked whether the 2026 out-of-sample errors were related to them.

| Idea | Test | Outcome |
|---|---|---|
| Heat build-up, degree-days, consecutive hot days | Correlation with residuals; walk-forward second-stage GBM on residuals | Weak relation (abs. correlation ≤ 0.17); second stage **worsened** D+1 MAE by 4.0% (95% CI +11 to +167 MW) |
| Operator-bias regime (3-day vs 28-day bias) | Same second stage | Errors are 23–33% larger after a sign flip, but the direction is not predictable; no gain |
| Hour/calendar recalibration | Same second stage, calendar only | Small gain at D+2 only (−3%, 95% CI −164 to −4 MW) |
| Fuzzy-logic risk score (heat, bias flip, holiday) | Adaptive band width; fuzzy weight on the bias correction | Band worse on the Winkler score (+120 MW at D+1, +432 MW at D+2, both significant); weight neutral (+0.2%) |
| Shorter bias-correction windows (7, 14 days) | Re-selection on 2025 and 2026 | The 28-day window remained best in both years |

The interpretation is that the temperature terms already in the model capture most of the weather signal,
and the remaining error is closer to noise than to a missing variable. Further gains need **new information**,
such as fresher weather runs or state-level holidays, rather than a different regression.

## 6. Live replay: November 4–10, 2026

Each day was re-forecast as of 10 pm the night before, with data cut at that time, archived weather and
frozen recipes.

| | Model MAE | Benchmark MAE | Result | Days won | Peak hour (±1 h) |
|---|---|---|---|---|---|
| D+1 | 2,349 MW | 2,139 MW | lost 9.8% | 4 of 6 | 6 of 6 |
| D+2 | 3,329 MW | 4,157 MW | won 19.9% | 4 of 7 | 7 of 7 |

**What happened at D+1:**
- **A heat wave:** Southeast capitals reached 33–37 °C, and load responded more strongly than history suggested.
- **The weather forecast was not the problem:** temperature errors stayed around ±0.7 °C per day.
- **The operator's bias flipped sign:** the Southeast schedule went from 1–2.6 GW above actual in October to 2.6–2.8 GW below in early November. The 28-day correction kept removing the old positive bias, which doubled the error.

**Response:** we kept the model unchanged, because tuning to one week would be overfitting. A sign flip
between the 3-day and 28-day operator bias is reported as a **risk alert** for the desk.

## 7. Limitations

- **Short selection window:** public DESSEM data start in May 2025, so recipes were chosen on seven months.
- **Holidays:** the model knows only national holidays; the operator also knows regional and company schedules.
- **Price:** the official spot price (CCEE) was not reachable from the project's network (HTTP 403), so price is estimated from CMO with regulatory floor and cap. Because the price sat at the floor in 82% and 98% of hours in 2022 and 2023, the project forecasts net load rather than price.
- **Weather data:** archived forecasts have roughly 25–110 km resolution, and the free Open-Meteo tier is licensed for non-commercial use only.
- **Revised data:** the backtest uses revised verified data, while operations see the first, preliminary release.

## 8. Reproducibility and delivery

All steps run from scripts on a laptop:

- **Ingestion:** `pipeline.py` (scheduled every 15 minutes).
- **Backtests:** `carga_liquida_d1.py`, with `--horizonte 2` for D+2.
- **Operational forecast:** `prever_carga_liquida.py`.
- **Audit:** `auditar_previsoes.py`.
- **Diagnostics:** `scripts/diagnostico/`.
- **Dashboard:** a Power BI project kept as code (PBIP + TMDL, star schema, 53 DAX measures, 5 pages), generated by `exportar_bi.py` and `gerar_projeto_bi.py`.
- **Tests:** 91 offline tests, including leakage tests, run in CI.

## 9. Conclusion and future work

With open data and careful timing, a simple, well-benchmarked model beats the grid operator's own net-load
schedule by about 11% one day ahead. The edge rises to about 26% two days ahead, when the operator has not yet
seen the target day's weather. Most of the edge comes from archived weather forecasts and from correcting the
operator's systematic bias. More complex additions did not survive out-of-sample tests.

Next steps:
1. Link the D+2 net-load forecast to the estimated price and test whether benchmark errors anticipate price moves.
2. Use fresher weather runs (12–24 h newer) and state holidays.
3. Port the same architecture to Ontario (IESO), whose public demand forecasts must be archived daily because only a few months are kept.

## References and data

- ONS, *Dados Abertos* portal and load API (dados.ons.org.br).
- Open-Meteo, Historical Forecast and Previous Runs APIs (CC-BY 4.0).
- CPTEC/INPE MERGE precipitation; NOAA GFS; ECMWF Open Data (CC-BY 4.0); INMET automatic stations.
- Pedregosa et al. (2011), *Scikit-learn: Machine Learning in Python*, JMLR 12.
- Künsch (1989), *The jackknife and the bootstrap for general stationary observations*, Annals of Statistics (block bootstrap).
- Gneiting & Raftery (2007), *Strictly proper scoring rules, prediction, and estimation*, JASA (interval/Winkler score).
