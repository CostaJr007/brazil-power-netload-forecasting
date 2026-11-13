# Source and file evidence

| File | How to read it |
|---|---|
| ons_catalog.md | Descriptions and selection of every inventoried dataset |
| ons_resources.csv | Resources, formats and URLs returned by the catalog |
| acquisition_validation.json | Eight limited downloads and their checks |
| sample_coverage.json | Coverage and duplicate groups in the CSV samples |
| csv_parquet_comparison.json | Record and schema differences between formats |
| endpoints_audit.json | Details of recent URLs and internal dates read |
| endpoints_audit.md | Readable summary of that audit |
| load_api_probe.json | Responses from the one-off load API test |
| findings.md | Findings from the initial acquisition and their scope |
| weather_discovery.json | Official listings and inspection of the basin polygons |
| weather_acquisition.json | Manifests and internal metadata of the INPE/NOAA/INMET batch |
| weather_acquisition.md | Readable summary of the batch and its limits |
| weather_summary.json | Files, sizes, hashes and invalid geometries |
| pipeline_status.md / pipeline_status.json | State of the last run and Silver snapshot counts |
| windows_task.json | Windows task configuration and result of the test trigger |

The JSON files are audit evidence, not Gold tables. An HTTP 200 proves a response; a recent maximum date proves that reference is present, but not that every entity/period is complete.
