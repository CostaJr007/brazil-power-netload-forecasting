# Configuration

`ons.json` contains:

- `catalog_url`: base of the CKAN API used for metadata.
- `selected`: official dataset slugs that define the initial selection.

The slug is the dataset's text identifier, such as `balanco-energia-subsistema`. It is not necessarily the S3 folder name; the download URL comes from the catalog resources.

`meteorology.json` records sources, product type, access method, implementation status and quality caveats. It is a planning inventory, not a statement that every connector has already run.

JSON does not accept `#` comments like Python, so this README explains the fields without breaking the format read by the scripts. Never store passwords or tokens in these files.

`pipeline.json` defines collection frequencies, the revision window and the rejection threshold. These frequencies are project decisions, not promises about how often sources update. `ons_contracts.json` holds 36 initial schema contracts: required columns, numeric fields and the reference field. If a schema changes, review the contract before accepting the change.

`pld_limits.json` holds the regulator's yearly spot-price floor and cap, used to estimate the price from the marginal cost.
