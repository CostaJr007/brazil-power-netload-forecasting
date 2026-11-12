# Data sources and acquisition decisions

Full ONS metadata lives in `docs/inventory/ons_catalog.md` and `ons_resources.csv` (dataset titles are kept in
Portuguese, as published). The initial selection has 39 datasets and does not exclude the others.

## Energy and geography

| Family | Source and access | Status |
|---|---|---|
| Energy balance by subsystem (hourly load, wind, solar, hydro, thermal) | ONS CKAN → HTTP CSV/Parquet | Ingested since 2018; main target of the models |
| Reservoir storage (EAR) and natural inflow (ENA) by subsystem, basin, REE and reservoir | ONS yearly files | Ingested; used by the inflow models and the dashboard |
| Generation by plant, cluster and group | ONS monthly files | Ingested; some records are estimates, kept apart from observations |
| Scheduled and verified load | ONS load API (`apicarga.ons.org.br`), JSON, UTC | Ingested by load area; benchmark of the load model |
| Day-ahead schedule (DESSEM) and wind/solar schedules | ONS daily files | Ingested since 2025-05-23; benchmark of the net-load model |
| Curtailment (constrained-off), availability, interchange | ONS official files | Ingested for context and for the curtailment analysis |
| Reservoir, capacity and plant registries | ONS snapshots | Snapshotted periodically; some products have no history |
| Basin outlines | ONS `bacia_contorno` → shapefile ZIP | Ingested; six invalid geometries repaired explicitly |
| Detailed contributing areas | ANA BHO6 | Possible complement; no automatic mapping to ONS basins |
| Generation registry | ANEEL SIGA | Possible complement; identifier mapping must be audited |
| Official spot price (PLD) | CCEE | Connector ready but disabled: CCEE's firewall returns HTTP 403 to this network; price is estimated from CMO with the regulator's limits |

- Catalog: https://dados.ons.org.br/api/3/action/package_list
- Dataset metadata: https://dados.ons.org.br/api/3/action/package_show?id=balanco-energia-subsistema
- Example file: https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_2025.csv
- Basin polygons: https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/bacia_contorno/Bacias_Hidrograficas_SIN.zip
- Load API: `https://apicarga.ons.org.br/prd/cargaprogramada?dat_inicio=YYYY-MM-DD&dat_fim=YYYY-MM-DD&cod_areacarga=AREA` (and `cargaverificada`)

Load-area codes are taken from the official list, never guessed from SE/CO, S, NE or N.

## Weather

Structured inventory: `configs/meteorology.json`; first-batch evidence in [weather_acquisition.md](inventory/weather_acquisition.md).

| Product | Access | Use and caveats |
|---|---|---|
| INMET stations | Yearly ZIPs, https://portal.inmet.gov.br/dadoshistoricos | Observed temperature; gaps, sentinels, station moves |
| INPE MERGE | https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/ | Observed daily rain, 0.1°; an estimate, not a point measurement |
| NOAA GFS | https://nomads.ncep.noaa.gov/ | 24/48/72 h forecasts; cycle and lead time change availability |
| ECMWF IFS Open Data | https://www.ecmwf.int/en/forecasts/datasets/open-data | 15-day forecasts (GRIB2); the public archive is rolling, not full history |
| Open-Meteo Previous Runs and Forecast API | https://open-meteo.com | Forecasts **as issued** 48/72/96 h ahead and live forecasts at plant and city points; CC-BY 4.0, non-commercial |
| ERA5 / ERA5-Land, NASA IMERG, CHIRPS, NOAA GEFS | Copernicus CDS, NASA, UCSB, NCEI | Researched as optional comparators; not ingested |
| ANA HidroWeb | https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html | Requires registration; not ingested |

Archived forecasts are what make the backtest honest: each feature uses the forecast that existed at decision time,
not the observed weather or a reanalysis.

## Caveats documented by ONS

- Hourly hydraulic data: not consolidated, agents' responsibility, possible gaps; end-of-hour timestamps. https://dados.ons.org.br/dataset/dados_hidrologicos_ho
- Daily hydraulic data: consolidated and revisable. https://dados.ons.org.br/dataset/dados-hidrologicos-res
- Generation by plant: includes clusters/groups; some records are forecasts. https://dados.ons.org.br/dataset/geracao-usina-2
- Reservoir registry: no history in the current product. https://dados.ons.org.br/dataset/reservatorio
- Catalog update dates do not prove when observations were published.
- Found in this project: on 3 days of 2026 the hourly balance lost most Northeast wind generation (telemetry outage); see [results.md](results.md).
