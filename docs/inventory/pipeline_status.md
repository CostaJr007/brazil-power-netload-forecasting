# Pipeline status

Checked: 2026-11-13T13:14:42.880234+00:00; run: 20261113T125931-fed26170 (success, 15 min ago); overall status: **success**.

Task Scheduler: last run 2026-11-13T08:14:29.0000000-05:00, code 267009; next 2026-11-13T08:29:28.0000000-05:00.

| Dataset | Resource snapshots | Valid rows | Rejected |
|---|---:|---:|---:|
| ecmwf_ifs_0p25 | 75 | 4343625 | 0 |
| automatic_stations_annual | 9 | 45026904 | 0 |
| merge_daily | 3237 | 785697567 | 21 |
| gfs_0p25 | 54 | 11467170 | 0 |
| balanco-energia-subsistema | 10 | 432239 | 0 |
| balanco_dessem_detalhe | 532 | 99917 | 0 |
| balanco_dessem_geral | 7 | 1344 | 0 |
| capacidade-geracao | 1 | 5827 | 10 |
| carga-energia-programada | 294 | 399840 | 0 |
| carga-energia-verificada | 468 | 623048 | 0 |
| carga-energia | 9 | 12948 | 0 |
| cmo-semanal | 9 | 1852 | 0 |
| cmo-semi-horario | 7 | 473664 | 0 |
| curva-carga | 9 | 310752 | 0 |
| cvu-usitermica | 1 | 4630 | 0 |
| dados-hidrologicos-res | 44 | 2429359 | 0 |
| dados_hidrologicos_ho | 1 | 50295 | 0 |
| disponibilidade_usina | 1 | 45156 | 0 |
| ear-diario-por-bacia | 9 | 76046 | 0 |
| ear-diario-por-ree-reservatorio-equivalente-de-energia | 9 | 38844 | 0 |
| ear-diario-por-reservatorio | 1 | 23864 | 0 |
| ear-diario-por-subsistema | 9 | 12948 | 0 |
| ena-diario-por-bacia | 9 | 76046 | 0 |
| ena-diario-por-ree-reservatorio-equivalente-de-energia | 9 | 38844 | 0 |
| ena-diario-por-reservatorio | 1 | 48670 | 0 |
| ena-diario-por-subsistema | 9 | 12948 | 0 |
| energia-vertida-turbinavel | 1 | 40124 | 0 |
| fator-capacidade-2 | 63 | 13305271 | 0 |
| geracao-termica-despacho-2 | 1 | 38424 | 0 |
| geracao-usina-2 | 63 | 46405453 | 0 |
| grandezas_fluviometricas | 25 | 315541 | 0 |
| intercambio-nacional | 2 | 65280 | 0 |
| programacao_diaria | 7 | 1429200 | 0 |
| programacao_x_previsao | 7 | 203664 | 0 |
| res_cotaareavolume | 1 | 9154684 | 0 |
| res_volumeespera | 1 | 10158 | 0 |
| reservatorio | 1 | 162 | 0 |
| restricao_coff_eolica_detail | 1 | 569184 | 0 |
| restricao_coff_eolica_usi | 62 | 13452192 | 0 |
| restricao_coff_fotovoltaica_detail | 32 | 21019248 | 0 |
| restricao_coff_fotovoltaica | 32 | 3143952 | 0 |
| usina_conjunto | 1 | 2159 | 0 |
| usina_pqu | 1 | 1318 | 0 |

Counts must not be summed as if they were one table or energy measures. Products and periods may overlap.

Blocked sources:

- **ccee_pld**: HTTP 403 from the CCEE firewall for the outbound IP on 2026-11-10 (including www.ccee.org.br). Connector ready with ccee.enabled=false; enable it when the network has access. Meanwhile, the ONS half-hourly/weekly CMO is the available reference (hourly PLD = DESSEM CMO clipped to the ANEEL-regulated minimum/maximum PLD; it does not replace the official series).
- **era5_ecmwf_gefs_ana**: Connectors not enabled in this version. ERA5/ECMWF require a local CDS account and key.
