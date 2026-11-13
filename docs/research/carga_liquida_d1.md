# D+1 net load vs the ONS day-ahead schedule (DESSEM)

Question: can tomorrow's net load (load − wind − solar) be forecast better than the schedule ONS publishes the day
before? It is the most direct "alpha" question that public data allows.

Script: `scripts/carga_liquida_d1.py`. Results: `docs/inventory/carga_liquida_results.json`.
Row-level forecasts: `data/gold/previsoes_carga_liquida.parquet`.

## Data cleaning (before any ML)

Done in `models.dados.tratar_balanco` and `carregar_dessem`; affects fewer than 1% of hours. Bad values become
missing, never zero.

- **Night-time solar:** solar above 50 MW between 8 pm and 4:59 am local time becomes missing (e.g. SE in 2022–23).
- **Frozen values:** wind or solar identical for 4 h or more above 50 MW becomes missing (e.g. SE solar stuck at 2,876 MW all night on 2024-11-10; North wind).
- **Zero load:** becomes missing (e.g. South on 2018-11-04).
- **Half-published DESSEM:** 136 subsystem-days between Jul 2025 and Jan 2026; only hours with both half-hours are used.
- **Physically impossible forecasts:** negative radiation and cloud cover outside 0–100% are clipped.

## Design

- **Target:** the ONS hourly balance (`vw_balanco_carga_liquida`). Solar includes utility plants and rooftop (distributed) generation.
- **Benchmark:** the DESSEM schedule (`balanco_dessem_detalhe`) by subsystem and hour: load = `val_demanda`, wind = `val_ger_eolica`, solar = `val_ger_fotovoltaica + val_ger_mmgd`. Available since 2025-05-23.
- **Allowed information:** only what exists on the evening of T−1: verified generation and load up to T−2, and GFS/ECMWF forecasts issued 48 h before each hour (`previous_day2`), capacity-weighted over plant cells.
- **Models per component:** per-hour Ridge and gradient boosting on the ratio `y / level`, where level is the 28-day mean of the same hour up to T−2; blends with the ONS schedule; quarterly refit.
- **Honest selection:** for each component the recipe is chosen on 2025 data (May 31 – Dec 31) and frozen; 2026 (to Nov 7) is used only for confirmation.
- **Test:** 95% interval from a 14-day block bootstrap on the MAE difference.

## Two findings before any ML

1. **DESSEM has a level bias against the balance.** In 2026 the mean ONS error (forecast − actual) was:

   | Component | Subsystem | Mean bias |
   |---|---|---|
   | Load | SE | +1,153 MW |
   | Load | NE | +391 MW |
   | Solar | SE | +419 MW |

   Part of it is a definitional difference between schedule and verified data. A desk would correct this bias before
   any ML, so the fair benchmark is the **bias-corrected ONS schedule**: the schedule minus the mean error of the last
   28 days at the same hour, known up to T−2 (`models.renovaveis.corrigir_vies`).
2. **Subsystem errors cancel out nationally.** Cross-subsystem error correlations are between −0.10 and 0.24; the
   sum of subsystem MAEs is 4,125 MW but the national MAE is 2,369 MW. Winning in every subsystem does not guarantee
   winning nationally.

## Results by component (2026 confirmation, MAE in MW)

| Component | ONS | Bias-corrected ONS | Recipe chosen on 2025 | Recipe MAE | Gain vs ONS |
|---|---|---|---|---|---|
| Load | 727 | 560 | mean(ML, corrected ONS) | 512 | 29.6% |
| Wind | 434 | 434 | mean(ML, corrected ONS) | 397 | 8.5% |
| Solar | 315 | 241 | corrected ONS | 241 | 23.6% |

- **Load:** ML adds about 8% beyond the bias correction; forecast temperature carries most of the weight.
- **Wind:** DESSEM has no bias. ML alone loses to ONS (−2.5% to −9.6%), but the blend with ONS gains 8.5%, with a 95% CI excluding zero.
- **Solar:** ML (Ridge on forecast radiation and cloud cover) only ties with ONS; all the gain comes from correcting the bias.

## Results on net load

**Frozen recipe, national grid (MAE, MW):**

| | ONS | Bias-corrected ONS | Component recipe |
|---|---|---|---|
| 2025 (selection) | 1,961 | 1,738 (+11.4%) | 1,702 (+13.2%) |
| 2026 (confirmation) | 2,371 | 2,214 (+6.6%) | 2,104 (+11.2%) |

These figures use the common sample where every candidate model has a value; the dashboard, which uses every
available hour, shows 2,110 vs 2,373 MW (11.1%).

**Tests on 2026 (MAE difference, 95% CI):**

| Comparison | MAE difference | 95% CI |
|---|---|---|
| Recipe − ONS | −238 MW | [−385, −101] |
| Recipe − corrected ONS | −94 MW | [−171, −19] |

The gain beyond the bias correction, about 4.2%, is small but statistically different from zero.

**By subsystem** (2026, gain vs ONS): SE +28.0%, N +14.1%, NE +9.9%, S +4.4%. Against the corrected schedule the
recipe wins in all four, with 95% CIs excluding zero.

**By hour band** (national, 2026, gain vs ONS):

| Band | Gain |
|---|---|
| Solar hours, 10 am – 3 pm | +15.7% |
| Peak, 4–9 pm | +12.7% |
| Morning | +9.6% |
| Overnight | +6.7% |
| Evening | +5.0% |

The daily ramp (max − min of the day) also improves: its error falls from 3,080 MW (ONS) to 2,695 MW.

**By month:** the gain concentrates from March to July (+14% to +34%). In August, September and November 2026 the
recipe loses to ONS (−2% to −6%): the Northeast high-wind season, when wind error dominates.

## What did not work

- **Pure ML without the ONS schedule as input:** loses to ONS nationally (−12.7% in 2026). With public weather forecasts, the ONS schedule carries information we cannot reproduce: curtailment plans, dispatch and the operator's own wind forecasts.
- **Gradient boosting on solar:** much worse than Ridge while the `y/level` ratio was uncapped (at dawn the level is near zero and the ratio explodes). The target is now capped at 3, and gradient boosting still does not beat Ridge.
- **Equal weight across subsystems:** the South barely gains (+4.4%).

## Market reading (honest)

- **This is forecast alpha, not D+1 price alpha.** Tomorrow's spot price comes from DESSEM itself, already published the day before, so a better D+1 net load does not anticipate that price. The value lies elsewhere:
  - intraday positioning and renewable curtailment risk;
  - reading the deviation between scheduled and verified values, which feeds settlement charges;
  - input for D+2 onwards, where no schedule exists yet (see [carga_liquida_d2.md](carga_liquida_d2.md)).
- **Short selection data:** 7 months of 2025, because public DESSEM starts on 2025-05-23. With more history the recipes may change.
- **More than half of the gain is bias correction.** Simple, but exactly the adjustment a desk makes before any sophisticated model.
- **Weather forecasts:** Open-Meteo (CC-BY 4.0, non-commercial). Commercial use would require a licence or own data.
