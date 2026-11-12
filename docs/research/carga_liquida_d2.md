# D+2 net load: before ONS publishes its schedule

Follow-up of [carga_liquida_d1.md](carga_liquida_d1.md). At D+1 the ONS schedule (DESSEM) is already published and
tomorrow's price comes from it. At **D+2** no schedule exists yet: a good forecast here anticipates the information
that will set that day's price.

Command: `scripts/carga_liquida_d1.py --horizonte 2`. Results: `docs/inventory/carga_liquida_dmais2_results.json`.
Row-level forecasts: `data/gold/previsoes_carga_liquida_dmais2.parquet`.

## What is known at decision time (10 pm on day D, target T = D+2)

| Information | Available up to | At D+1 it was |
|---|---|---|
| Verified load, wind and solar | T−3 (D−1) | T−2 |
| ONS schedule | only T−1 (tomorrow) | T itself |
| Weather forecast | run issued 72 h before each hour (`previous_day3`) | 48 h |

The 72 h and 96 h forecasts were downloaded with `--dias 3 4` in both download scripts.

Tests guarantee that changing data for T−2, T−1 or T does not change any feature used to forecast T, e.g.
`test_d_mais_2_nao_usa_geracao_de_t_menos_2`, `test_carga_d_mais_2_nao_usa_carga_de_t_menos_2`,
`test_ons_ant_em_d_mais_2_e_a_programacao_de_t_menos_1` and the weekday-bias tests.

## The benchmark: what a desk would do without a model

Use tomorrow's schedule (`ons_ant`) as the forecast for the day after. Three versions were tested:

| Benchmark (national, 2026) | MAE (MW) |
|---|---|
| `ons_ant`: T−1 schedule, unadjusted | 4,722 |
| `ons_ant_corrigido`: minus the mean bias at the same hour | 4,655 |
| **`ons_ant_semana`**: minus the bias at the same hour **and weekday** (last 4 occurrences) | **3,501** |

- **The raw version is too weak.** On a Monday it uses Sunday's schedule. A first test against `ons_ant_corrigido` showed a 42% gain, too high to be fair.
- **The official benchmark is `ons_ant_semana`**, which fixes exactly that weekday switch (`models.renovaveis.corrigir_vies_semana`).

## Results (recipe chosen on 2025, confirmed on 2026)

**Components (2026, MAE in MW):**

| Component | Benchmark `ons_ant_semana` | Recipe chosen on 2025 | MAE | Gain |
|---|---|---|---|---|
| Load | 847 | mean of Ridge and GBM | 602 | 29.0% |
| Wind | 696 | GBM | 469 | 32.6% |
| Solar | 373 | mean(ML, benchmark) | 302 | 19.0% |

**Net load, national grid:**

| | Benchmark | Recipe | Gain | Same-day ONS schedule (published later), corrected |
|---|---|---|---|---|
| 2025 (selection) | 2,937 | 2,246 | 23.5% | 1,763 |
| 2026 (confirmation) | 3,501 | 2,594 | **25.9%** | 2,211 |

- **Test on 2026:** recipe − benchmark = −892 MW, 95% CI [−1,195, −580].
- **Gain in every subsystem,** CIs excluding zero: N +26.8%, NE +27.8%, S +28.4%, SE +27.9%.
- **By hour band:** evening +37%, peak +34%, overnight +27%, morning +23%, solar hours +15%.
- **By month:** gain in 10 of 11 months; the exception is August (−2.6%).
- The dashboard, which uses every available hour, shows 2,607 vs 3,534 MW (26.2%).

**Cost of deciding a day earlier:** the D+2 recipe errs 461 MW more (95% CI [299, 636]) than the same-day corrected
ONS schedule, which ONS publishes a day later; it is still close to the raw ONS schedule (2,366 MW).

## Anticipating the ONS schedule

This is the market use. The target is no longer the verified value but the schedule ONS will publish tomorrow for
T, which is the input to T's price.

| Forecast of T's schedule (national, 2026) | MAE (MW) |
|---|---|
| T−1 schedule, raw | 3,983 |
| Benchmark `ons_ant_semana` | 3,021 |
| **Component recipe** | **2,256** |

The recipe anticipates the ONS schedule with 25% less error than the best simple benchmark.

## Honest reading

- **Almost all the gain comes from the 72 h weather forecast.** The benchmark does not know the weather for the day after tomorrow; the model does. Without weather (`ridge_sem_previsao`), ML loses to the benchmark on wind and solar.
- **Wind shows it clearly.** At D+1 ML only helped when blended with ONS. At D+2 yesterday's schedule knows nothing about the wind front two days out, and gradient boosting gains 33% on its own.
- **For solar, the T−1 schedule still carries useful information:** the recipe is the mean of ML and the benchmark.
- **Same limits as D+1:** short selection sample (public DESSEM starts on 2025-05-23), coarse weather grid, Open-Meteo for non-commercial use only.
- **This is not price yet.** The next step is linking the D+2 net-load forecast to the estimated CMO/PLD (`vw_pld_estimado_horario`) and testing whether the net-load error anticipates price moves.
