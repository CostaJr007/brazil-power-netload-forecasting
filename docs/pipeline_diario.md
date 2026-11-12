# Daily acquisition and processing pipeline

A single entry point, `scripts/pipeline.py`: collection and Bronze preservation → Silver processing → publication
of approved snapshots and reports → Gold views.

## Cadence and publication

Task Scheduler calls the program every 15 minutes. The program decides which sources are due, with a small clock
tolerance so that a trigger is not missed by a few seconds.

| Source / product | Query policy | Evidence about publication |
|---|---|---|
| ONS hourly hydraulic data | Every 15-minute tick | ONS states updates every 15 min |
| The other 36 ONS contracts (incl. `cmo-semanal`) | About every hour | Different times per product; no single schedule assumed |
| **Scheduled** load (API, ONS forecast) | Every hour, D and D+1, per subsystem SECO/S/NE/N | D+1 appears the day before; an empty D+1 response means "not published yet" |
| **Verified** load (API, actual + distributed generation) | Every 6 h, last 7 days | Released ~03:00 UTC the next day and **revised** later (`din_atualizacao`); each revision becomes a new Bronze object |
| CCEE (official spot price) | Disabled (`ccee.enabled=false`) | CCEE's firewall returned 403 to the egress IP; the connector is ready for when access is granted |
| MERGE daily rain | Every hour, re-checking the last three days | The file is discovered in the official directory, not inferred from the clock |
| GFS | Every hour, checking 00/06/12/18 UTC cycles and 24/48/72 h leads | A cycle is collected only once announced |
| ECMWF IFS Open Data | Every hour, 00z run, 24–360 h leads (rain, 2 m temperature, runoff) | The `.index` file lists messages; only the needed variables are downloaded by byte range. The origin keeps only ~12 runs |
| Gold (basin averages + DuckDB views) | At the end of every run with new Silver | `scripts/gold.py`; see [gold_views.md](gold_views.md) |
| INMET yearly ZIP | Daily | A consolidated product; daily queries do not create daily observations |

ONS daily data declares updates at 09:15, 14:15 and 17:00. Hourly querying is a project choice, not a guarantee of
immediate capture at those minutes; the policy lives in `configs/pipeline.json`.

Sources: [ONS hourly](https://dados.ons.org.br/dataset/dados_hidrologicos_ho), [ONS daily](https://dados.ons.org.br/dataset/dados-hidrologicos-res), [NOAA NOMADS](https://nomads.ncep.noaa.gov/), [INMET history](https://portal.inmet.gov.br/dadoshistoricos).

## Commands

```powershell
.\.venv\Scripts\python.exe scripts/pipeline.py --offline     # process everything already in Bronze, no network
.\.venv\Scripts\python.exe scripts/pipeline.py               # update due sources and process new content
.\.venv\Scripts\python.exe scripts/pipeline.py --force       # re-query every task now (unchanged files stay cached)
.\.venv\Scripts\python.exe scripts/pipeline.py --tasks ons   # run one group when it is due
.\.venv\Scripts\python.exe scripts/status_pipeline.py
```

The job is protected by a process lock; only one run at a time, and Windows ignores overlapping triggers too. If the
lock is busy, the new run logs it and exits with 0 (not a failure). A failure never becomes a success: the report is
`partial`, the process returns 1 and independent sources keep being tried. Unexpected errors also produce a `partial`
report instead of disappearing.

`status_pipeline.py` raises `attention` when the last report is late (more than two ticks) or when Task Scheduler
recorded a non-zero code, which catches runs that die midway and never write a report.

## History (backfill)

The daily pipeline only looks at recent days. For models and backtests use `scripts/backfill.py`, which **plans by
default** and downloads only with `--execute`:

```powershell
.\.venv\Scripts\python.exe scripts/backfill.py --sources ons,load --start 2018-01-01             # plan only: files and sizes
.\.venv\Scripts\python.exe scripts/backfill.py --sources ons,load --start 2018-01-01 --execute   # refuses above --max-gb (default 10)
.\.venv\Scripts\python.exe scripts/backfill.py --sources merge --start 2025-01-01 --end 2025-12-31
```

- Uses its own lock (`data/backfill.lock`), so the daily schedule keeps running in parallel.
- Load API in monthly blocks per area (≈100× fewer calls than day by day).
- Report in `data/runs/backfill_<run_id>.json`; does not overwrite `runs/latest.json`.
- GFS has no history on NOMADS (~10 days); archived forecasts come from Open-Meteo Previous Runs.
- Daily and monthly load windows can overlap: deduplicate by `(cod_areacarga, din_referenciautc)` keeping the latest `source_updated_at_utc` / `_available_at_utc`.

`--force` ignores cadence but never quality tests. `--offline` does not update the query state of sources.
`build_contracts.py` generated the 36 initial contracts from audited schemas; it must not run automatically to accept
unknown schema changes.

## Processing rules

### ONS files

- Checks the expected columns and logs new ones.
- Trims strings, including codes such as `N ` and `S `.
- Numeric types defined by contract, with decimal-comma conversion.
- Keeps `val_tipoperda` as a category, although its name starts with `val_`.
- Removes only fully duplicated rows; never picks arbitrarily between conflicting values of the same key.
- Identifies the national (SIN) aggregate without adding it to the four regions.
- Unparseable values and unknown codes go to quarantine.
- Storage above 100% is flagged in `_quality_warnings` and preserved (the source has such cases); never truncated.
- Inflow as % of the long-term mean can normally exceed 100.

ONS timestamps stay in `_event_time_source`, not converted to UTC while the convention is unconfirmed;
`_timezone_status` makes that explicit.

### ONS load API (scheduled and verified)

- The only ONS data with a **declared time zone**: `din_referenciautc` is UTC and marks the **end** of the half hour. Silver creates `interval_end_utc` and `interval_start_utc` (= end − 30 min).
- `dat_referencia` is the Brazilian operating date, so the collection's "today" uses UTC−3.
- Verified load includes `val_cargammgd` (distributed generation) and `val_cargaglobalsmmgd` (load without it).
- `source_updated_at_utc` comes from `din_atualizacao` and selects the latest revision.
- The same area and interval repeated in one response go to quarantine (`duplicate_key`).
- Zero total load gets a `zero_total_load` warning without deletion. The API's `SIN` area returns only zeros and is excluded: sum SECO+S+NE+N.

### MERGE / GFS GRIB

- Converts messages into a long table with variable, value, unit, latitude and longitude.
- Kelvin → Celsius; kg/m² of water → mm; pressure stays in Pa and radiation in W/m².
- Keeps wind levels separate.
- Preserves run, valid time and `startStep/endStep`; different rain intervals are never summed together.
- MERGE is read through its CTL descriptor (PREC/NEST).
- Does not invent a MERGE daily window: flags `closure_unverified` until the closing time is confirmed.

### INMET

- Reads each CSV member of the ZIP separately to limit memory.
- Normalises column names, decimals and timestamps explicitly labelled UTC.
- `-9999` becomes null; missing values never become zero and are not interpolated.
- Keeps accumulated radiation in kJ/m², not confused with W/m² flux.

## Storage layout

```text
data/
  bronze/                         originals and manifests, unchanged
  silver/<source>/<dataset>/<resource>/<version>/<hash>/
    *.valid.parquet               approved records
    *.quarantine.parquet          rejected records and reasons
    snapshot.json                 publication and quality marker
  silver/current.json             index of the current approved snapshots
  gold/energia.duckdb             views only
  bi/                             star-schema tables for Power BI
  pipeline.sqlite                 last query per task and resource state
  runs/<run_id>.json              report of each finished run
  runs/latest.json                latest run
  runs/pipeline.log / scheduler.log
```

On the development machine `data/` is a Windows junction to another drive; the code always uses `data/` (or
`ENERGY_DATA_DIR`). Anyone cloning the repository does not need this: `data/` is git-ignored and created on first run.

Do not read `data/silver/**/*.parquet` as one table: it mixes history, versions, sources and quarantine. Use
`current.json` and select the `.valid.parquet` files of the dataset you need.

Each snapshot carries the source hash, resource identifier and `_available_at_utc`, the first proven collection of
that content in this environment. The index keeps the last approved snapshot if a new version fails.

The transformation version depends on contracts, the quality threshold and the `silver.py` code (frequencies and notes
do not reprocess Silver). The default rejection threshold is 1% of a file; above it, the snapshot is `quality_failed`
and does not replace the last approved one. The threshold is never raised to hide source failures.

## Windows scheduling

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_pipeline_task.ps1              # install or update
Get-ScheduledTaskInfo -TaskName Energy-Data-Pipeline
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_pipeline_task.ps1 -Uninstall   # remove, keeping data
```

The task runs under the current account, without stored passwords or admin rights, hidden, at logon and every 15
minutes. **The computer must be on, logged in and online** — this is not 24/7 hosting. Missed triggers run when
possible, and the short look-back recovers part of late publications.

The `run_pipeline.ps1` wrapper redirects output through `cmd.exe`: in PowerShell 5.1, redirecting a native
executable's stderr with `ErrorActionPreference=Stop` turned the first log line into an exception and killed Python
midway (fixed on 2026-11-10).

The job covers 37 tabular ONS products, both load APIs (SECO/S/NE/N) and MERGE/GFS/INMET/ECMWF. Still blocked: CCEE
(firewall 403) and ERA5/GEFS/ANA (connectors not implemented); see `blocked_sources` in `configs/pipeline.json`.
