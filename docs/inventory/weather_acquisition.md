# Meteorologia: dados efetivamente adquiridos

Verificação UTC: 2026-11-10T13:05:16.215944+00:00. Arquivos: 13. Bytes originais: 87,708,195.

| Origem | Produto | Arquivo/consulta | Situação |
|---|---|---|---|
| inpe | merge_daily | [fonte](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261103.grib2) | readable |
| inpe | merge_daily | [fonte](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261104.grib2) | readable |
| inpe | merge_daily | [fonte](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261105.grib2) | readable |
| inpe | merge_daily | [fonte](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261106.grib2) | readable |
| inpe | merge_daily | [fonte](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261107.grib2) | readable |
| inpe | merge_daily | [fonte](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261108.grib2) | readable |
| inpe | merge_daily | [fonte](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261109.grib2) | readable |
| inpe | merge_documentation | [fonte](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/2026/11/MERGE_CPTEC_20261109.ctl) | readable |
| inpe | merge_documentation | [fonte](https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/MERGE_READ-ME.pdf) | readable |
| noaa | gfs_0p25 | [fonte](https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?file=gfs.t00z.pgrb2.0p25.f024&dir=%2Fgfs.20261110%2F00%2Fatmos&subregion=&leftlon=-72.75&rightlon=-36.25&bottomlat=-31.75&toplat=2.75&var_UGRD=on&var_VGRD=on&var_TMP=on&var_PRES=on&var_APCP=on&var_DSWRF=on&lev_100_m_above_ground=on&lev_10_m_above_ground=on&lev_2_m_above_ground=on&lev_surface=on) | readable |
| noaa | gfs_0p25 | [fonte](https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?file=gfs.t00z.pgrb2.0p25.f048&dir=%2Fgfs.20261110%2F00%2Fatmos&subregion=&leftlon=-72.75&rightlon=-36.25&bottomlat=-31.75&toplat=2.75&var_UGRD=on&var_VGRD=on&var_TMP=on&var_PRES=on&var_APCP=on&var_DSWRF=on&lev_100_m_above_ground=on&lev_10_m_above_ground=on&lev_2_m_above_ground=on&lev_surface=on) | readable |
| noaa | gfs_0p25 | [fonte](https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?file=gfs.t00z.pgrb2.0p25.f072&dir=%2Fgfs.20261110%2F00%2Fatmos&subregion=&leftlon=-72.75&rightlon=-36.25&bottomlat=-31.75&toplat=2.75&var_UGRD=on&var_VGRD=on&var_TMP=on&var_PRES=on&var_APCP=on&var_DSWRF=on&lev_100_m_above_ground=on&lev_10_m_above_ground=on&lev_2_m_above_ground=on&lev_surface=on) | readable |
| inmet | automatic_stations_annual | [fonte](https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip) | readable |

## Conteúdo e escopo

- MERGE: 7 arquivos diários, referências ['20261103', '20261104', '20261105', '20261106', '20261107', '20261108', '20261109'], grade original 0,1°, com CTL e manual. O CTL declara PREC (precipitação) e NEST (número de estações por ponto); a rotulagem genérica rdp/prmsl não define a natureza do produto. Metadados originais preservados.
- GFS: rodada 2026-11-10, ciclo 0 UTC; 3 arquivos para horizontes 24/48/72 h. Grade 0,25°, retângulo das bacias com margem. Componentes de vento a 10/100 m e temperatura a 2 m conferidos; há pressão, precipitação e radiação.
- INMET: 634 membros CSV; 634 cadastros lidos. Membro amostrado: INMET_CO_DF_A001_BRASILIA_01-01-2026_A_31-10-2026.CSV; referências 2026/01/01 a 2026/10/31. Não certifica cobertura uniforme das demais estações.
- Geografia: 31 feições ONS; 6 geometrias inválidas. Vínculo candidato de 210 estações com bacias válidas. As inválidas foram excluídas só da consulta espacial; fonte original preservada.
- Manual MERGE de 26/05/2025: documenta a nova base baseada em IMERG V07B e histórico reprocessado desde 1998. A mesma nomenclatura de arquivo não garante a mesma versão do processamento. A convenção precisa do fechamento diário permanece para confirmação antes de agregar por dia civil.

## Limites para a próxima etapa

O lote é inicial. Os três horizontes GFS são instantes espaçados, não uma previsão horária contínua. O recorte das bacias não garante cobertura de todos os parques eólicos/solares; a localização dos ativos será um cadastro separado.
A precipitação GFS contém mensagens com diferentes startStep/endStep: selecionar uma mensagem por intervalo antes de somar. Unidades foram preservadas, incluindo Kelvin, Pa, kg/m², m/s e W/m². Radiação média em W/m² não é diretamente a radiação acumulada em kJ/m² publicada pelo INMET.
Não foram calculadas médias de chuva por bacia, reparadas geometrias, preenchidas lacunas ou removidos valores. A Silver permanece uma fase posterior. ERA5/CDS, GEFS, ECMWF e ANA ainda não têm aquisição executada nesta entrega.

## Reproduzir

```powershell
.\.venv\Scripts\python.exe scripts/discover_weather.py
.\.venv\Scripts\python.exe scripts/download_weather.py
.\.venv\Scripts\python.exe scripts/report_weather.py
```

As listagens oficiais foram preservadas em data/weather_catalog. Os originais meteorológicos estão em data/bronze/inpe, data/bronze/noaa e data/bronze/inmet, com manifestos e histórico SQLite.