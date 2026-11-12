# Solar plants, irradiance and load seasonality

Analysis of 2026-11-10. Numbers in `docs/inventory/solar_usinas.json`, `solar_irradiancia.json` and
`sazonalidade_carga.json`; code in `scripts/solar_usinas.py`, `scripts/solar_irradiancia.py` and `models/sazonalidade.py`.

## Where the plants are

The ONS dataset `fator-capacidade-2` lists solar plants with coordinates: 99 clusters, about 25.5 GW. The total may
be slightly overstated because of duplicated names (Rio Brilhante appears twice). Rooftop generation is not included.

| State | Capacity (MW) |
|---|---|
| MG | 9,626 |
| BA | 3,445 |
| PI | 2,775 |
| CE | 2,516 |
| RN | 2,088 |

The full ranking, with latitude and longitude, is in `solar_usinas.json`.

## Best irradiance source: the plant's own measurement

`restricao_coff_fotovoltaica_detail` (April 2024 onwards) has measured irradiance, generation and a curtailment flag.

| Test | Result |
|---|---|
| Satellite/reanalysis radiation (NASA POWER) × generation | Correlation 0.35–0.6; barely beats climatology |
| Measured irradiance × generation, all hours | 0.38–0.82 |
| Measured irradiance × generation, **uncurtailed hours only** | **0.84–0.97 in 11 of 12 plants** |
| Generation estimated from irradiance, Jan 2026 onwards | Cuts climatology error by 36–87% in 8 of 9 plants |

**Reading:** sunlight explains generation when the plant is allowed to generate. The weak correlation came mainly
from curtailment and from the flattened curve of tracker plants. Assu Sol is an exception (0.57, no gain) and its
sensor deserves a check. The measurement only exists after the fact: forecasting still needs an irradiance forecast.

**Curtailment:** the share of daytime hours with recorded restriction rose from 5–21% in mid-2024 to 60–80% in much of
2025 and 2026. Two caveats: an hour counts if at least one plant in the cluster was restricted (an upper bound), and
the plant set changes as many plants enter later. It concentrates between 8 am and 1 pm. The field
`corte_pct_da_referencia_quando_informada` does not measure the yearly loss, because the reference generation is filled
in only part of the hours.

## Solar seasonality (mean of plants with history, NASA POWER)

| Month | kWh/m²/day | Clearness (actual ÷ clear sky) | Capacity factor |
|---|---|---|---|
| January | 5.93 | 0.75 | 23.2% |
| April | 5.51 | 0.84 | 21.9% |
| June | 4.79 | 0.88 | 19.1% |
| September | 6.57 | 0.93 | 22.0% |
| November | 6.32 | 0.81 | 24.1% |

June has the least sun; September the most sun and the clearest sky. In summer the potential is high but clouds
reduce the yield.

## Sliced load model (confirmation on 2025 and 2026)

Training one model per season or per month window **did not beat the single model** overall: MAPE 2.69% and 2.65%
vs 2.67%, with confidence intervals including zero. The single model was chosen on 2023 and 2024.

| Slice | ONS | Single model |
|---|---|---|
| Winter | 2.61% | 2.31% |
| Autumn | 3.06% | 2.56% |
| Spring | 3.10% | 2.53% |
| Summer | 3.54% | 3.41% |
| December | 4.31% | 4.41% |
| Overnight (0–5 am) | 2.26% | 2.32% |
| Solar hours (10 am – 3 pm) | 4.28% | 3.45% |
| Peak (4–9 pm) | 2.76% | 2.30% |
| Holidays | 3.66% | **5.26%** |
| South in summer | 4.66% | **5.52%** |

**Weak spots:** holidays and the South in summer, where ONS is better. In the South's winter the month-window model
fell from 3.81% to 3.14%, but that observation was made after looking at the data and must be tested before adoption.

## Load seasonality (monthly index, 2022–2025)

| Subsystem | Peak month | Trough month |
|---|---|---|
| SE/CO | March (1.08) | July (0.92) |
| South | February (1.14) | May (0.93) |
| Northeast | November (1.06) | July (0.93) |
| North | October (1.09) | January (0.92) |
