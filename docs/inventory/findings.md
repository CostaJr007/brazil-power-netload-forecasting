# Initial acquisition results

Source: real calls to the CKAN API and official HTTP downloads in this session. Structured evidence in acquisition_validation.json, sample_coverage.json and csv_parquet_comparison.json.

## Catalog

**Scope: full inventory of the catalog metadata, with sample validation of the files. There was no accessibility audit of the 15,002 resources, no full paginated scan of the bucket and no proof that every series is updated/corrected.**

- 88 datasets resolved without error through package_list + package_show.
- 15,002 resources cataloged; they include alternative formats, dictionaries and potentially repeated resources.
- 39 datasets selected for the project's acquisition.
- Scraping was not needed. Terminal access required network authorization outside the sandbox; that is a property of this session's environment, not an ONS requirement.

A later query to the S3 root via ListObjectsV2 (max-keys=5) returned HTTP 200, IsTruncated=true and a continuation token. So opening the root does not inventory the whole bucket. The query was only a listing test, without reading the returned objects; a data audit must use the dataset/ prefix and walk every page. LastModified indicates an object change, not the latest reference date of the records.

## Samples

| Sample | Result |
|---|---|
| Balance 2025 CSV | 43,800 records; N, NE, S, SE and SIN, 8,760 distinct timestamps in each group |
| Balance 2025 Parquet | Same schema and same records as the CSV, by EXCEPT ALL in both directions with DuckDB types |
| EAR 2025 CSV | 1,460 records; four groups, 365 distinct dates per group |
| ENA 2025 CSV | 1,460 records; four groups, 365 distinct dates per group |
| Basin ZIP | 1,622,722 bytes; CRC verified; .shp, .shx, .dbf, .prj, .cpg and .qmd present |
| JSON dictionaries | Daily schedule and scheduled/verified load downloaded and decoded |

The three CSV samples showed no duplicate groups on the proposed key (subsystem, reference). 2025 coverage found in the balance: 01/01 00:00 to 31/12 23:00; EAR/ENA: 01/01 to 31/12. This does not prove physical validity of the values, historical latency or the quality of other years.

## Two concrete issues for the Silver layer

1. **SIN is already in the balance.** Summing every subsystem row without separating this aggregate can count the total twice.
2. **Keys with trailing spaces.** EAR and ENA carry `N ` and `S ` in the samples, while the balance has `N` and `S`. The original bytes are preserved; an explicit normalization rule is needed for joins.

## Later findings (2026-11-10, pipeline and backfill)

| Finding | Where | Handling |
|---|---|---|
| Load API requires `cod_areacarga`; without it, it returns an empty list | apicarga | Confirmed codes: SECO, S, NE, N (+ state areas) |
| Verified load area `SIN` returns **all values as zero** | apicarga | Excluded from collection; `zero_total_load` alert in Silver |
| **Invalid JSON** from 2018 to Feb/2019: empty MMGD fields written as `"field": ,` | apicarga verified | Tolerant parsing only for this pattern (becomes `null`); original bytes intact |
| Verified load is **revised** later (`din_atualizacao`) | apicarga | Each revision is a new object; views pick the latest |
| `val_intercambioprogmwmed` missing in the 2023 files | intercambio-nacional | Column marked `optional` in the contract |
| 6 of the 31 basin geometries self-intersect | bacia_contorno | `make_valid`, area change 0.000% |
| CCEE firewall returns 403 (including the main site) | CCEE | Connector disabled until access is available |

## Still not validated live

- Equivalence between the load API and the CSVs of other products (different granularities and components).
- Time zone of the ONS file products (only the load API declares UTC).
- Mapping between basins, reservoirs, plants and incremental areas (5 polygons not linked to ENA).
- Real schema of the CCEE PLD datasets.

Original state of this section (start of the project): the four acquisition tests passed, with Python 3.13.13 and DuckDB 1.5.6. Today the suite has 91 tests.
