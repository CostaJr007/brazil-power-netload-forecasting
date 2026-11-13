# Results on one page

What the project delivers, how it was measured and where the details are. All model numbers come from a
**walk-forward backtest**: the model "recipe" is chosen on one period (2025) and scored on a later one
(2026). 95% intervals come from a 14-day block bootstrap. Each fold trains only on targets that were already
published when its first day is forecast.

> **2026 is a validation year, not a pristine test set.** Several checks (bias-correction window, residual
> models, fuzzy bands) were run on 2026 after the recipes were chosen, so repeated looks may flatter it slightly.
> The recipes are now frozen; the daily operational forecasts stored from Nov 2026 onwards are the clean test.

## The question

Brazil's short-term price (CMO/PLD) comes out of the grid operator's day-ahead schedule (DESSEM), which
balances **net load** (load − wind − solar) with hydro, thermal and interchange. A trading desk gains an
edge when it anticipates net load better than the public references, or before they are published.

## Headline numbers

| Forecast | Benchmark (what is already free) | Result | Details (PT) |
|---|---|---|---|
| **Net load D+1**, national grid, hourly | ONS day-ahead schedule (DESSEM) corrected by its 28-day bias | **−5.0% MAE** in 2026 (2,097 vs 2,207 MW; 95% CI of the difference −172 to −21 MW). Against the raw schedule: −11.3% (2,364 MW), of which 6.6 points are the bias correction alone | [carga_liquida_d1.md](research/carga_liquida_d1.md) |
| **Net load D+2**, national grid, hourly | Previous-day schedule corrected by hour and weekday | **−25.7% MAE** in 2026 (2,602 vs 3,500 MW; CI −1,186 to −575 MW); anticipates the schedule ONS has not yet published with 25% less error | [carga_liquida_d2.md](research/carga_liquida_d2.md) |
| Load D+1, by subsystem | ONS scheduled load (API) | −22% MAE nationally; −26 MW/h beyond bias correction | [carga_d1.md](research/carga_d1.md) |
| River inflow (ENA) by basin, 1–14 days after the last published value | Persistence | 30.5% (1 day), 19.3% (3), 14.1% (7), 14.8% (14) with memory and observed rain; ENA is published the next morning, so the effective lead is about a day shorter | [modelagem_meteorologia_energia.md](research/modelagem_meteorologia_energia.md) |

> **What the D+1 recipe is.** Load and wind: 50/50 blend of ML (Ridge + boosting) with the bias-corrected DESSEM. Solar: the bias-corrected DESSEM alone. ML on its own loses to the operator at D+1 for wind and solar, so the D+1 result is "operator + bias correction + a modest ML blend". At D+2, pure ML wins for load and wind.
>
> **Two ways of counting.** The research tables score every candidate on the same sample of hours; the dashboard uses every available hour (D+1: 2,102 vs 2,209 MW, −4.9%; D+2: 2,614 vs 3,534 MW, −26.0%). Both are out of sample.

## Where the model does not win (2026, national grid)

- **D+1, solar hours (11 am – 3 pm):** the bias-corrected DESSEM is better than the recipe in every one of these hours.
- **D+1, weekends:** a tie (2,243 vs 2,229 MW). Holidays are the hardest days, though the recipe still beats the benchmark there.
- **D+1, by month:** loses in February, August and September (−1% to −8%), the Northeast high-wind season.
- **D+1, days won:** 59% of days; at D+2, 68%. D+2 loses only in August (−3%).

## What we learned (useful for any desk)

1. **Correct the operator's bias before any ML.** The DESSEM schedule runs about 1.15 GW above verified load in the Southeast; that correction alone gains 6.6% nationally at D+1, more than the ML blend adds on top (5.0%). Part of this gap may be definitional (DESSEM demand vs. balance load), which was not verified.
2. **Forecast temperature is what moves load.** Reservoirs, inflows and past generation added nothing to D+1 load.
3. **The value of weather forecasts grows with the horizon.** At D+1 ML only helps when blended with the operator; at D+2 yesterday's schedule does not know about the wind front, and the model gains 33% on wind.
4. **Subsystem errors cancel nationally.** Winning in every region does not guarantee winning in total, so the national grid is scored separately.
5. **The price is censored.** In 2022–2023, 82% and 98% of hours sat at the regulatory floor, which is why the project forecasts net load (what moves price) rather than price directly.
6. **Curtailment is large.** In 2025–26, 19–20% of possible wind and 26% of solar output was curtailed; the recent level used as the model's base already embeds this.

## From backtest to operations

`scripts/prever_carga_liquida.py` produces the real forecast for tomorrow and the day after, by subsystem and
hour, with the frozen recipes and the current weather forecast at plant locations.

- **If yesterday's balance is not yet published** (around 7:50 pm Brasília time), the day is forecast with the next horizon, which needs less information; the horizon used is recorded in the output.
- **80% prediction band:** each forecast carries a range taken from the backtest errors of the previous 120 days that were already known at decision time (empirical Monte Carlo). In 2026 it covered 79.3% (D+1) and 79.5% (D+2) of hours. Example, national grid on Nov 13, 2026: average 59.6 GW, band 56.8–64.2 GW, peak at 7 pm.
- **Dashboard:** `scripts/exportar_bi.py` builds the star schema and `bi/Energia.pbip` opens the Power BI project ([bi/README.md](../bi/README.md)).

## Week replay: Nov 4–10, 2026

`scripts/auditar_previsoes.py` rebuilds each forecast with data cut at 10 pm the night before, archived weather
forecast and frozen recipes, then compares with what happened. It is a **replay**, not a true as-of run: the
inputs are today's revised ONS values cut by date, not the exact vintages that existed that night.

| | Model (national MAE) | Benchmark | Result | Days beating | Peak hour (±1 h) |
|---|---|---|---|---|---|
| **D+1** | 2,349 MW | bias-corrected ONS 2,232 MW (raw 2,139 MW) | **lost 5.2%** (9.8% vs raw) | 4 of 6 | 6 of 6 |
| **D+2** | 3,329 MW | bias-corrected T−1 schedule 4,157 MW | **won 19.9%** | 4 of 7 | 7 of 7 |

- **What went wrong at D+1:** the model under-forecast all week, mostly Southeast load (−1.5 GW). Southeast capitals hit 33–37 °C between Nov 3 and 7; load responded to heat more than history taught, and ONS under-forecast too. The temperature forecast itself was accurate (±0.7 °C/day).
- **The operator's bias flipped sign:** in October the Southeast schedule ran 1–2.6 GW above actual; on Nov 2 and 4 it ran 2.8 and 2.6 GW below. The 28-day correction kept removing the old bias and doubled the error. Nov 2 was a public holiday, a known weak spot.
- **Shorter correction windows were tested:** 28 days is still best on 2025 and 2026, and even a 7-day window would not have beaten raw ONS that week. **Nothing was changed:** tuning to one bad week would be overfitting.
- **D+2 behaved like the backtest:** 20% gain vs 26% expected. Peak hour was right every day on both horizons.

## Is a new model worth it? Residual diagnostics on 2026

`scripts/diagnostico/residuos_2026.py` relates the out-of-sample error of the current recipe (304 days of 2026)
to candidate variables before any retraining.

- **Heat:** a Southeast pattern exists (under-forecast on the hottest days: −297 MW at D+1, −654 MW at D+2), but the relationship is weak (|correlation| ≤ 0.18).
- **Operator bias flip:** errors are 23–34% larger on those days, but the direction is not predictable.
- **Second-stage walk-forward model with these variables:** worse national MAE (+3.9% with weather at D+1, 95% CI +5 to +163 MW). Only an hour/calendar recalibration helped slightly at D+2 (−2.9%, CI −160 to −5 MW).
- **Fuzzy logic** (`scripts/diagnostico/fuzzy_banda.py`): a fuzzy risk score (heat, bias flip, holiday) neither separated large errors nationally nor improved the band (Winkler score +125 MW at D+1 and +472 MW at D+2, both significant). The simple per-hour band stays.
- **Conclusion:** the temperature terms already in the model capture almost all the signal. Heat build-up and bias regime are useful as **risk alerts**, not as corrections. The next real gain needs **new information** (fresher weather runs, state holidays), not a different regression.

## Data quality (before any model)

- **Night-time solar and frozen values** in the ONS balance become missing (under 1% of hours).
- **Half-published DESSEM schedules** (136 subsystem-days): only complete hours are used.
- **Last day of the balance** is preliminary and stays out of the backtest.
- **Verified-load revisions** are each preserved in Bronze.
- **ONS telemetry outages:** on 3 days of 2026 (Jan 16, Mar 7, May 9) the published balance lost most Northeast wind (0.2–0.5 GW reported vs ~12 GW scheduled by ONS itself). They are **kept** in the headline numbers, which are therefore conservative; excluding them, the dashboard gain rises from 4.9% to 5.4% at D+1 and from 26.0% to 27.5% at D+2. The dashboard flags these days and leaves them out of the daily bias chart.
- **Weather forecasts** are **archived as issued** (Open-Meteo Previous Runs), not reanalysis, so there is no hidden "perfect forecast".

## Honest limitations

- **Short selection period:** public DESSEM starts on 2025-05-23, so recipes were chosen on 7 months.
- **Holidays:** the load model errs more (5.3% vs 3.7% for ONS); the operator knows company schedules.
- **Official spot price:** CCEE blocks the egress IP (HTTP 403), so price is estimated from marginal cost with the regulator's limits.
- **Weather grid** is about 110 km. Open-Meteo is free for **non-commercial** use only; commercial production would need a licence or another source.
- **First publication:** in operations the last verified day is preliminary, while the backtest used revised values.
- **ENA horizon:** daily ENA is published the morning after, so "1 day ahead" counts from the last published day; the effective lead time is about a day shorter.

## Next steps

1. Link the D+2 net-load forecast to the estimated price (`vw_pld_estimado_horario`) and test whether the benchmark's net-load error anticipates price moves.
2. Add a second market, **Ontario (IESO)**, reusing the same architecture: archive IESO demand forecasts daily (they are only kept for a few months), Environment Canada and archived GEM forecasts, and score D+1 demand against IESO.
