# Fontes e decisão de aquisição

Verificação: 2026-11-09. Os metadados integrais do ONS estão em docs/inventory/ons_catalog.md e ons_resources.csv; a seleção inicial tem 39 conjuntos e não descarta os demais.

## Energia e geografia

| Família | Fonte e acesso | Decisão |
|---|---|---|
| Balanço por subsistema | ONS CKAN → HTTP CSV/Parquet | Primeira amostra baixada em ambos os formatos |
| EAR/ENA por subsistema | ONS → arquivos anuais | Primeiras amostras CSV baixadas |
| EAR/ENA por bacia, REE e reservatório | ONS → arquivos e dicionários | Catalogados; amostras pendentes |
| Geração por usina, conjunto e grupo | ONS → arquivos mensais conforme recursos | Catalogado; preservar distinção entre observado e estimado |
| Carga programada/verificada | apicarga.ons.org.br; JSON | Dicionários baixados; dados da API ainda não validados |
| Programação e previsão eólica/solar | ONS → arquivos diários | URLs resolvidas; dicionário de programação baixado |
| Constrained-off, disponibilidade, intercâmbios | ONS → arquivos oficiais | Coletar para contextualizar geração entregue |
| Cadastros de reservatórios, capacidade, usina/conjunto | ONS → snapshots | Preservar mudanças; alguns produtos não têm histórico |
| Cota–área–volume | ONS res_cotaareavolume | Catalogado; dicionário e conteúdo ainda não inspecionados |
| Contornos de bacias | ONS bacia_contorno → ZIP shapefile | Baixado; CRC e presença dos componentes verificados; geometria/CRS pendentes |
| Áreas contribuintes detalhadas | ANA BHO6 | Complemento, não correspondência automática com bacias ONS |
| Cadastro de geração | ANEEL SIGA | Complemento planejado, correspondência de IDs deve ser auditada |
| PLD | CCEE | Fonte complementar planejada; conector e autenticação/download a validar separadamente |

ONS catálogo: https://dados.ons.org.br/api/3/action/package_list

Metadados por conjunto: https://dados.ons.org.br/api/3/action/package_show?id=balanco-energia-subsistema

Exemplo real descoberto (corrige caminhos anteriormente sugeridos no chat):
https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/balanco_energia_subsistema_ho/BALANCO_ENERGIA_SUBSISTEMA_2025.csv

Polígonos:
https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/bacia_contorno/Bacias_Hidrograficas_SIN.zip

Endpoints de carga informados na descrição dos recursos:
https://apicarga.ons.org.br/prd/cargaprogramada?dat_inicio=YYYY-MM-DD&dat_fim=YYYY-MM-DD&cod_areacarga=AREA
https://apicarga.ons.org.br/prd/cargaverificada?dat_inicio=YYYY-MM-DD&dat_fim=YYYY-MM-DD&cod_areacarga=AREA

O código de área não deve ser adivinhado a partir de SE/CO, S, NE ou N. Confirmar lista de áreas, limites, autenticação e envelope de resposta antes de coletar em lote.

## Meteorologia

Fontes estruturadas: configs/meteorology.json. Atualização em 10/11/2026: primeiro lote INMET/MERGE/GFS baixado e inspecionado, com evidências em [weather_acquisition.md](inventory/weather_acquisition.md). As demais fontes permanecem apenas pesquisadas/documentadas.

| Produto | Acesso | Disponibilidade/qualidade a conferir |
|---|---|---|
| INMET estações | ZIPs anuais, https://portal.inmet.gov.br/dadoshistoricos | Falhas, sentinelas, alturas, unidades, deslocamentos de estação |
| ANA HidroWeb | https://www.ana.gov.br/hidrowebservice/swagger-ui/index.html | Requer acesso cadastrado; guardar nível de consistência e estação |
| INPE MERGE | https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/ | Grade, versão, acumulação e arquivo README; estimativa não é medição pontual |
| NOAA GFS | https://nomads.ncep.noaa.gov/ | HTTP/GRIB filter; ciclo e lead alteram disponibilidade; comando retangular preparado |
| NOAA GEFS | https://www.ncei.noaa.gov/products/weather-climate-models/global-ensemble-forecast | Arquivo histórico tem mudanças de resolução; não misturar versões/membros |
| ECMWF IFS/ENS | https://www.ecmwf.int/en/forecasts/datasets/open-data | GRIB2; arquivo público recente é rotativo, não histórico completo |
| ERA5 e ERA5-Land | https://climate.copernicus.eu/climate-reanalysis | CDS/conta/licença; reanálise retrospectiva; latência e provisório/final |
| NASA IMERG | https://gpm.nasa.gov/data/imerg | Early/Late/Final separados; avaliar autenticação por canal |
| UCSB CHIRPS | https://www.chc.ucsb.edu/data/chirps3 | Escolher versão; preliminar e final têm disponibilidade distinta |

Priorizar MERGE + INMET observados, NOAA GFS/GEFS previstos e ERA5/ERA5-Land históricos. ECMWF complementa as previsões após definir o modo de acesso ao histórico. NASA/CHIRPS são comparadores opcionais, evitando baixar coleções redundantes antes de dimensionar volume.

A documentação ECMWF consultada informa arquivo rotativo de 12 rodadas e resoluções IFS 0,25° e 0,1° com horários de disponibilização diferentes. Registrar esses parâmetros em cada coleta; não fixar uma única resolução como se valesse para todo o histórico.

Geografia complementar ANA: https://www.gov.br/ana/pt-br/assuntos/noticias-e-eventos/noticias/base-de-dados-geoespaciais-da-ana-permite-gestao-mais-eficiente-das-bacias-hidrograficas/

## Alertas documentados do ONS

- Hidráulica horária: não consistida, responsabilidade dos agentes, possíveis lacunas; hora final. https://dados.ons.org.br/dataset/dados_hidrologicos_ho
- Hidráulica diária: consolidada e revisável. https://dados.ons.org.br/dataset/dados-hidrologicos-res
- Geração por usina: inclui conjuntos/grupos; alguns registros são previsão. https://dados.ons.org.br/dataset/geracao-usina-2
- Cadastro de reservatórios: sem histórico no produto atual. https://dados.ons.org.br/dataset/reservatorio
- Precipitação ONS 2020–2021: descontinuada. https://dados.ons.org.br/dataset/precipitacao-estacao
- Data de atualização dos metadados não prova data de publicação de observações.

Não atribuímos nota numérica à qualidade sem medir as amostras. A verificação de reputação institucional e de documentação está separada da qualidade observada dos arquivos.
