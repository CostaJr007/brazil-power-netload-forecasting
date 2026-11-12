# Modelling: weather → basins → inflow (ENA) and load

First modelling round, 2026-11-10. Code in `models/`, run with `scripts/modelagem.py`, full numbers in
`docs/inventory/model_results.json`.

## Why this target

Price depends on how much water reaches the reservoirs (natural energy inflow, ENA) and on how much load the system
serves, so both are modelled before price.

Little is public about how Brazilian trading desks model this. One generator describes a platform with
[inflow forecasts over three planning horizons](https://www.zedudu.com.br/novo-sistema-com-ia-da-axia-energia-pode-elevar-geracao-de-energia-em-mais-de-12/)
and [AI applied to weather models](https://agenciainfra.com/blog/precos-da-energia-devem-seguir-pressionados-ate-janeiro-diz-axia/).
The project imitates the problem, not a known company method.

## Methods borrowed from earlier quant projects

| Origin | Mathematics | Use here | Outcome |
|---|---|---|---|
| Cointegration / stat-arb projects | Ornstein-Uhlenbeck, half-life ln2/θ | `models/timeseries.py`: mean reversion of the inflow anomaly | Useful baseline and a measure of each basin's memory |
| Athena-SDA | Kalman filter with innovation (NIS) | Time-varying-coefficient regression | **Worse than fixed Ridge** at every horizon |
| Athena-SDA | Past-only walk-forward, placebo tests | `models/validation.py` | **The most valuable item:** it overturned a wrong conclusion (see Load) |
| Volatility engine | GARCH | Not used | Inflow and load are level problems, not volatility problems |
| Options GEX project | Convexity | Deferred to the price stage | See `modelos_dos_repositorios.md`, section 4 |

The modules were rewritten for this problem, with no dependency on those repositories.

## Protocol

- **Yearly walk-forward:** each test year uses only models trained on earlier dates; means and climatology are also recomputed on training data only.
- **Perfect-foresight runs are labelled as such.** At the time the project held only 2 ECMWF and 8 GFS runs, so real forecasts could not be evaluated. The `*_cenario` models use the observed rain or temperature of the forecast period: they show the **upper bound** of the gain and are **not achievable performance**.
- **Confidence intervals:** 14-day block bootstrap.

## Inflow by basin (20 basins, 2021–2026)

Skill = share of the persistence error removed. The forecast is issued at t, with data up to t, for t+h.

| Model | h=1 | h=3 | h=7 | h=14 |
|---|---|---|---|---|
| Persistence MAE (average MW) | 147 | 374 | 629 | 867 |
| OU (current anomaly only) | 1.6% | 5.1% | 8.1% | 13.2% |
| Ridge, memory | 29.1% | 16.8% | 12.4% | 14.5% |
| **Ridge, memory + observed rain** | **30.5%** | **19.2%** | **14.1%** | **14.9%** |
| Kalman ARX | 5.9% | 1.0% | 1.8% | 3.0% |
| Boosting, memory + observed rain | 2.2% | −0.8% | −0.3% | 6.1% |
| *Bound: Ridge + perfect future rain* | *34.2%* | *32.6%* | *34.7%* | *36.0%* |

- **The per-basin linear model is the best achievable one,** with positive skill in every year and horizon. Pooled boosting loses: there are only ~8 years and trees do not extrapolate anomalies larger than those in training.
- **Observed rain helps a little:** 0.4–2.4 points over memory; significant at h=1, 3 and 7, not at h=14.
- **Rain forecasts have the largest potential:** perfect future rain lifts h=14 skill from 14.9% to 36.0%. Real gains will be smaller, because forecasts err, especially at long leads.
- **Heterogeneity:** at h=7 the achievable Ridge gain ranges from 22.5% (Grande) to −29.5% (Paraguaçu); Doce and Jequitinhonha sit near zero.
- **Placebo:** shuffling the rain lowers 1-day skill from 30.5% to 23.4%. The fairest control is the memory model, because the placebo loses two training years and adds noise.

## Daily load by subsystem (2022 – Oct 2026)

Forecast for day T issued on the morning of T−1, with verified load known up to T−2 (conservative). The competitor is
the ONS scheduled load, with a mean error (MAPE) of 2.72%.

| Model | MAPE | MAE reduction vs ONS |
|---|---|---|
| Same weekday last week | 4.15% | −72.6% |
| **ONS + mean error of the last 28 days** | **2.20%** | **20.7%** |
| ONS corrected by boosting | 2.25% | 17.4% |
| Boosting with calendar and past temperature | 2.42% | 2.2% |
| *Bound: corrected ONS + perfect temperature* | *1.96%* | *29.0%* |
| *Bound: boosting + perfect temperature* | *1.78%* | *32.8%* |

- **The simple rule beat machine learning.** Correcting the recent bias of the schedule beat the boosting model that corrects ONS (difference of 18 average MW, 95% CI 3 to 34).
- **The advantage is concentrated in 2022 and 2023:** the rule cut error by 42.7% and 28.5% in those years and only 0.4% in 2024. The ONS bias shrank, so future gains should not be extrapolated from the average.
- **Without ONS, the model is not enough in SE/CO:** boosting with calendar and past temperature is 12% worse than ONS in the largest subsystem.
- **Target-day temperature is what is missing.** It lowers boosting MAPE from 2.42% to 1.78%, but only with perfect foresight; the hourly D+1 model later confirmed the value of *forecast* temperature ([carga_d1.md](carga_d1.md)).

## Limitations

- **Scheduled load:** the API returns one version per interval, assumed to be the day-before schedule. If it is revised later, ONS looks better than it was and the models' real advantage would be larger.
- **Temperature:** mean of INMET stations in the 3 highest-load states of each subsystem, not population-weighted.
- **Data:** inflow is the current verified value; later ONS revisions are not reconstructed. Six basins only have data from 2026 and were left out, including Madeira and Xingu.
- **OU half-life in slow basins** (São Francisco: 268 days) reflects multi-year droughts and floods, not a quick return to the mean; it is not an operating horizon.

## Next steps, by value

1. **History of real rain and temperature forecasts,** which turns the bounds above into results. The daily collector already accumulates runs; reforecasts (GEFS, ECMWF) could speed this up.
2. **Aggregate inflow by subsystem** and use the cascade topology of the basins (Paraná and São Francisco should benefit).
3. **Price model:** CMO conditioned on forecast inflow, storage and net load, with the PLD limits applied afterwards.

Research sources: [IFMG study with LSTM for ENA and EAR](https://repositorio.ifmg.edu.br/items/17e8e09e-b8bf-400c-9d0e-fe27024677c8), [Unifei thesis on price and hydrological variables](https://repositorio.unifei.edu.br/jspui/bitstream/123456789/4124/1/Tese_2024041.pdf).
