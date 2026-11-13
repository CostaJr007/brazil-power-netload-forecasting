# Weather: data actually acquired

Checked UTC: 2026-11-13T13:13:07.948195+00:00. Files: 13. Original bytes: 87,708,195.

| Origin | Product | File/query | Status |
|---|---|---|---|
| inpe | merge_daily | [source](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261103.grib2) | readable |
| inpe | merge_daily | [source](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261104.grib2) | readable |
| inpe | merge_daily | [source](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261105.grib2) | readable |
| inpe | merge_daily | [source](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261106.grib2) | readable |
| inpe | merge_daily | [source](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261107.grib2) | readable |
| inpe | merge_daily | [source](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261108.grib2) | readable |
| inpe | merge_daily | [source](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261109.grib2) | readable |
| inpe | merge_documentation | [source](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261109.ctl) | readable |
| inpe | merge_documentation | [source](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/MERGE_READ-ME.pdf) | readable |
| noaa | gfs_0p25 | [source](https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?file=gfs.t00z.pgrb2.0p25.f024&dir=%2Fgfs.20261110%2F00%2Fatmos&subregion=&leftlon=-72.75&rightlon=-36.25&bottomlat=-31.75&toplat=2.75&var_UGRD=on&var_VGRD=on&var_TMP=on&var_PRES=on&var_APCP=on&var_DSWRF=on&lev_100_m_above_ground=on&lev_10_m_above_ground=on&lev_2_m_above_ground=on&lev_surface=on) | readable |
| noaa | gfs_0p25 | [source](https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?file=gfs.t00z.pgrb2.0p25.f048&dir=%2Fgfs.20261110%2F00%2Fatmos&subregion=&leftlon=-72.75&rightlon=-36.25&bottomlat=-31.75&toplat=2.75&var_UGRD=on&var_VGRD=on&var_TMP=on&var_PRES=on&var_APCP=on&var_DSWRF=on&lev_100_m_above_ground=on&lev_10_m_above_ground=on&lev_2_m_above_ground=on&lev_surface=on) | readable |
| noaa | gfs_0p25 | [source](https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?file=gfs.t00z.pgrb2.0p25.f072&dir=%2Fgfs.20261110%2F00%2Fatmos&subregion=&leftlon=-72.75&rightlon=-36.25&bottomlat=-31.75&toplat=2.75&var_UGRD=on&var_VGRD=on&var_TMP=on&var_PRES=on&var_APCP=on&var_DSWRF=on&lev_100_m_above_ground=on&lev_10_m_above_ground=on&lev_2_m_above_ground=on&lev_surface=on) | readable |
| inmet | automatic_stations_annual | [source](https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip) | readable |

## Content and scope

- MERGE: 7 daily files, references ['20261103', '20261104', '20261105', '20261106', '20261107', '20261108', '20261109'], original 0.1° grid, with CTL and manual. The CTL declares PREC (precipitation) and NEST (number of stations per point); the generic rdp/prmsl labels do not define the product. Original metadata preserved.
- GFS: run 2026-11-10, cycle 0 UTC; 3 files for 24/48/72 h leads. 0.25° grid, basin bounding box with margin. Wind components at 10/100 m and 2 m temperature checked; pressure, precipitation and radiation are present.
- INMET: 634 CSV members; 634 station records read. Sampled member: INMET_CO_DF_A001_BRASILIA_01-01-2026_A_31-10-2026.CSV; references 2026/01/01 to 2026/10/31. Does not certify uniform coverage of the other stations.
- Geography: 31 ONS features; 6 invalid geometries. Candidate link of 210 stations to valid basins. Invalid ones were excluded only from the spatial query; the original source is preserved.
- MERGE manual of 2025-05-26: documents the new base built on IMERG V07B and history reprocessed since 1998. The same file naming does not guarantee the same processing version. The exact daily closing convention still needs confirmation before aggregating by calendar day.

## Limits for the next stage

This is an initial batch. The three GFS leads are spaced instants, not a continuous hourly forecast. The basin box does not guarantee coverage of every wind/solar plant; asset locations will be a separate registry.
GFS precipitation contains messages with different startStep/endStep: select one message per interval before summing. Units were preserved, including Kelvin, Pa, kg/m², m/s and W/m². Mean radiation in W/m² is not directly the accumulated radiation in kJ/m² published by INMET.
No basin rain means were computed, geometries repaired, gaps filled or values removed. Silver is a later stage. ERA5/CDS, GEFS, ECMWF and ANA have no acquisition run in this delivery yet.

## Reproduzir

```powershell
.\.venv\Scripts\python.exe scripts/discover_weather.py
.\.venv\Scripts\python.exe scripts/download_weather.py
.\.venv\Scripts\python.exe scripts/report_weather.py
```

Official listings were preserved in data/weather_catalog. Weather originals are in data/bronze/inpe, data/bronze/noaa and data/bronze/inmet, with manifests and SQLite history.