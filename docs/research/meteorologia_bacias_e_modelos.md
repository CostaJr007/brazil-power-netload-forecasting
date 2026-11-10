# Meteorologia por bacia, fontes de fora e modelos de referência

Pesquisa de 10/11/2026. Objetivo: apoiar a **hipótese do projeto**, que é antecipar a ENA e a EAR (energia que chega e que está guardada nos reservatórios) a partir de chuva observada e prevista dentro dos polígonos das bacias, para ganhar vantagem nos modelos de energia. Ninguém confirmou que mesas de trading reais usam exatamente esta abordagem. Ela é uma escolha deste projeto, apoiada no que o próprio ONS e a literatura fazem.

**Legenda de acesso:** ✅ testado ao vivo nesta máquina · 🔑 exige cadastro ou token · ❓ não verificado.

## 1. Por que chuva por bacia

O ONS usa o modelo chuva-vazão **SMAP/ONS** desde 2009 para prever vazões nas semanas operativas. As entradas são vazão observada, **chuva observada e prevista** e evapotranspiração ([SBRH 2025](https://files.abrhidro.org.br/Eventos/Trabalhos/248/XXVI-SBRH0067-1-0-20250715-144029.pdf); [Alves, UFJF](https://repositorio.ufjf.br/jspui/bitstream/ufjf/16768/2/tiagodarochaalves.pdf)).

Documentos de grupo técnico citam chuva prevista Eta40 + GEFS em 2017–2018 e **ECMWF a partir de 2019**. Também citam a proposta de usar o **ECMWF com 51 membros** da 3ª à 6ª semana, com remoção de viés por *quantile mapping* ([Abraceel, GT CH 2023](https://abraceel.com.br/wp-content/uploads/post/2023/05/9a-Reuniao-GT-CH.pdf)).

A previsão de vazão alimenta o DECOMP/DESSEM, que calculam o CMO e o PLD. Quem prevê melhor a chuva por bacia antecipa a ENA e, com ela, o preço. É essa a ideia da hipótese.

## 2. Fontes de dados

### Bacias e hidrologia
| Fonte | O que traz | Acesso | Situação no projeto |
|---|---|---|---|
| ONS `bacia_contorno` | 31 polígonos de bacias do SIN | ✅ | Em uso; 6 geometrias reparadas com `make_valid` (variação de área 0,000%) |
| ONS ENA/EAR por bacia, REE e subsistema | Energia afluente e armazenada, diária | ✅ | Silver e Gold desde 2018 |
| ONS `dados_hidrologicos_ho/res` | Vazões e níveis por reservatório | ✅ | Silver (recente) |
| ANA HidroWebService (REST) | Séries de estações fluviométricas e pluviométricas | 🔑 token por e-mail a hidro@ana.gov.br ([manual](https://www.gov.br/ana/pt-br/assuntos/monitoramento-e-eventos-criticos/monitoramento-hidrologico/orientacoes-manuais/manuais/manual-hidrowebservice_publica.pdf)) | Não implementado: depende de credencial sua |
| ANA telemetria (SOAP legado) | Estações telemétricas | ❓ ([ServiceANA.asmx](https://telemetriaws1.ana.gov.br/ServiceANA.asmx)) | Alternativa sem token, a avaliar |
| CAMELS-BR | 897 bacias brasileiras com vazão, chuva e 65 atributos, pronto para ML | ✅ público ([artigo](https://essd.copernicus.org/articles/12/2075/2020/), [Zenodo](https://zenodo.org/record/3709337)) | Recomendado para pré-treinar modelos chuva-vazão |

### Chuva observada
| Fonte | Resolução | Acesso | Situação |
|---|---|---|---|
| **MERGE/CPTEC** (satélite GPM + pluviômetros) | 0,1°, diária | ✅ | Pipeline diário + backfill 2025→hoje; média por bacia na Gold |
| CHIRPS v2/v3 | 0,05° | ❓ (o caminho antigo devolveu 404; a estrutura mudou para `products/CHIRPS/`) | Alternativa |
| ERA5 / ERA5-Land (reanálise) | 0,25° / 0,1° | 🔑 conta CDS | Bloqueado: conta sua |

### Chuva prevista (meteorologia de fora)
| Fonte | O que traz | Histórico disponível | Acesso | Situação |
|---|---|---|---|---|
| **ECMWF IFS Open Data** | 0,25°, até 15 dias; inclui chuva, temperatura a 2 m, escoamento, vento a 100 m e radiação | Só as últimas ~12 rodadas | ✅ CC-BY-4.0, sem cadastro ([ECMWF](https://ecmwf.int/en/forecasts/datasets/open-data)) | **Implementado.** Rodada 00z, horizontes de 24 a 360 h |
| ECMWF AIFS (IA) | Mesmas variáveis, modelo por machine learning | ~12 rodadas | ✅ ([AIFS](https://www.ecmwf.int/en/forecasts/datasets/aifs-machine-learning-data)) | Próximo candidato: comparar IFS × AIFS por bacia |
| GFS (NOAA) | 0,25°, até 16 dias | ~10 dias no NOMADS | ✅ | Em uso, horizontes 24/48/72 h |
| GEFS (ensemble NOAA) | 31 membros, probabilístico | Tempo real na AWS (`noaa-gefs-pds`) | ✅ testado | Próximo candidato: incerteza da chuva |
| GEFSv12 reforecast | 11 membros, semanal, 2000–2019, até 35 dias | 20 anos | ✅ público ([AWS](https://registry.opendata.aws/noaa-gefs-reforecast/)) | **Chave para backtest honesto** de previsões |
| Open-Meteo (Previous Runs) | Previsão "como era" em D-1…D-7 por ponto | Desde ~2024 | ✅ testado, gratuito para uso não comercial ([docs](https://open-meteo.com/en/docs/historical-forecast-api)) | Útil para validar; é agregador, não a fonte primária |
| GloFAS (Copernicus) | **Vazão prevista** global, 30 dias, ensemble | Reforecasts de 20 anos; tempo real desde 2020 | 🔑 conta CDS ([Harrigan et al. 2023](https://hess.copernicus.org/articles/27/1/2023/)) | Referência de comparação para a ENA |

**Cuidado com o backtest.** Para testar o modelo, use a previsão **como estava disponível no dia**. A *Historical Forecast API* do Open-Meteo junta as primeiras horas de cada rodada, o que se parece com uma observação. Usar isso como "previsão" vaza informação do futuro. Por isso o pipeline guarda cada rodada do ECMWF e do GFS a partir de agora, e o GEFSv12 reforecast cobre o passado.

## 3. Modelos e artigos de referência

### Chuva → vazão (prever a ENA)
- **SMAP/ONS:** modelo conceitual usado pelo operador. É o baseline natural a vencer.
- **LSTM chuva-vazão** (Kratzert et al.): uma única LSTM treinada em muitas bacias superou modelos hidrológicos calibrados, inclusive em bacias sem medição. Biblioteca aberta: [NeuralHydrology](https://neuralhydrology.github.io/categories/code). Base global: **Caravan**, com 6.830 bacias e CAMELS-BR incluído ([ESSD](https://essd.copernicus.org/articles/17/4613/2025/essd-17-4613-2025-relations.html)).
- **Google Flood Forecasting** ([Nearing et al., Nature 2024](https://www.nature.com/articles/s41586-024-07145-1.pdf)): duas LSTMs em sequência, uma para o tempo passado (*hindcast*) e outra para o tempo previsto (*forecast*), com atributos estáticos da bacia. É uma arquitetura direta para "chuva prevista por bacia → vazão".
- **LSTM com CAMELS-BR e ECMWF/CFSv2** ([EGU21](https://meetingorganizer.copernicus.org/EGU21/EGU21-7138.html)): o desempenho depende bastante da fonte de chuva usada. É um argumento a favor de comparar MERGE, ECMWF e GFS.

### Países com matriz parecida (forte participação hídrica)
- **Noruega / Nord Pool:** pós-processamento de ensembles hidrológicos com BMA para afluência ([NTNU](https://ntnuopen.ntnu.no/ntnu-xmlui/handle/11250/2603824)); ML com decomposição de sinal para afluência de curto prazo ([Sci. Reports 2023](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10148885/)); previsões S2S do ECMWF para afluência de até 6 semanas, com valor econômico estimado ([arXiv](https://arxiv.org/pdf/2108.06269)).
- **Canadá / Hydro-Québec:** LSTM treinada em reforecasts ensemble do ECMWF para volumes afluentes de 14 a 45 dias ([EGU25](https://presentations.copernicus.org/EGU25/EGU25-7194_presentation.pdf); [Martel, ÉTS](https://espace.etsmtl.ca/3780/1/MARTEL_Dylane.pdf)). Um multimodelo com conceituais e deep learning reduziu o CRPS em até 45% até 9 dias ([Armstrong, ÉTS](https://espace.etsmtl.ca/3441/1/ARMSTRONG_William.pdf)).
- **Nova Zelândia:** SDDP aplicado ao sistema neozelandês (DOASA) e risco de afluência ([Philpott, EPOC](https://www.epoc.org.nz/workshops/DER18/Andy.pdf)). O regulador explica como a escassez de água eleva o preço ofertado ([Electricity Authority](https://www.ea.govt.nz/news/eye-on-electricity/hydro-storage-limits-and-why-rain-matters-for-electricity)).
- **Colômbia (hidrotérmica com ENSO):** RF, LSTM e MLP para vazão em 4 bacias de UHEs, com piora em eventos ENSO ([Dyna 2024](https://doaj.org/article/9e888d9e9975478b8b7763dd0065e677)); ML e regressão quantílica para o preço spot em função dos reservatórios ([ZBW](https://savearchive.zbw.eu/bitstream/11159/7820/1/1775488454_0.pdf)).

### Brasil: preço (PLD/CMO) com ENA e EAR
- Modelo híbrido estocástico + rede neural para preços forward, com a ENA como variável dos reservatórios ([Albani et al., Energy Economics 2025](https://ideas.repec.org/a/eee/eneeco/v148y2025ics0140988325004785.html)).
- MLP multivariado para PLD semanal como alternativa ao DECOMP ([Energies](https://mdpi.com/1996-1073/17/8/1864)).
- LSTM × ARIMA para o PLD do SE com PLD, ENA, EAR e carga ([USP](https://bdta.abcd.usp.br/directbitstream/6070ae91-4ba5-43db-bc0e-8cdbd049c229/PABLO%20NABIL%20VILLAR%20BOU%20AS...)).
- Projeto aberto: LightGBM para PLD semanal com EAR, ENA e defasagens ([GitHub](https://github.blesdmm.dns-dynamic.net/felipefl142/brazilian-energy-price-forecasting)). Serve de referência de portfólio.

## 4. Como isso vira pipeline (o que já está feito)

```
MERGE (obs)  ─┐                                     ┌─ vw_chuva_observada_bacia_diaria
ECMWF (prev) ─┼─► Silver (grade) ─► basins.py ─► Gold ┼─ vw_previsao_chuva_bacia (rodada × horizonte)
GFS (prev)   ─┘          pesos por área (EPSG:5880)  └─ vw_chuva_x_ena_bacia (chuva × ENA, por dia)
```

- `scripts/basins.py`: reparo de geometria, pesos por área da célula dentro do polígono e média ponderada que ignora células sem valor e informa a cobertura.
- `scripts/gold.py`: um Parquet por snapshot e as views no `data/gold/energia.duckdb`.
- `configs/basin_mapping.json`: liga os nomes dos polígonos aos nomes da ENA (24 automáticos, 2 exceções justificadas, 5 sem correspondência).

## 5. Próximos passos sugeridos (fase de dados)
1. **GEFSv12 reforecast** (2000–2019) recortado por bacia: o histórico de previsões para o backtest.
2. **ECMWF AIFS** ao lado do IFS, para comparar modelos físico e de IA por bacia.
3. **ANA HidroWebService** (pedir o token) para vazões de postos e para ligar postos a usinas.
4. **Correspondência usina → bacia → REE**, para ligar as 5 bacias restantes e somar ENA por subsistema.
5. **ERA5-Land / GloFAS** (conta CDS) como reanálise e vazão de referência.

Só depois disso começa a fase de modelagem (SMAP como baseline → LSTM tipo hindcast/forecast → previsão de ENA → modelo de preço).
