# Energy — plataforma de aquisição de dados

**Para estudar o código:** leia o [guia de estudo em português](docs/guia_de_estudo.md). Os 12 arquivos Python próprios receberam comentários sobre instruções, funções, entradas/saídas e efeitos. O mapa de scripts está em [scripts/README.md](scripts/README.md), e as consultas em [docs/sql_do_projeto.md](docs/sql_do_projeto.md).

Projeto de engenharia de dados do setor elétrico brasileiro. Primeiro descobrir, obter e auditar os dados. Depois construir Silver/Gold. Pesquisa estatística é uma fase independente, consumindo publicações versionadas.

**Pipeline diário ativo:** coleta e tratamento até a Silver foram implementados e executados contra as fontes reais. A tarefa Windows `Energy-Data-Pipeline` está registrada a cada 15 minutos; usa políticas próprias por fonte. Consulte o [guia do pipeline diário](docs/pipeline_diario.md), o [estado da Silver](docs/inventory/pipeline_status.md) e a [evidência do agendamento](docs/inventory/windows_task.json). Gold/modelagem continuam futuras.

```powershell
.\.venv\Scripts\python.exe scripts/pipeline.py
.\.venv\Scripts\python.exe scripts/status_pipeline.py
# Histórico: só planeja; acrescente --execute para baixar (plano 2018→hoje ≈ 1,5 GB)
.\.venv\Scripts\python.exe scripts/backfill.py --sources ons,load --start 2018-01-01
```

**Atualização 10/11/2026 (tarde):**
- **API de carga destravada.** Códigos oficiais confirmados ao vivo: SECO, S, NE, N. A carga **programada** (previsão do ONS, D e D+1) e a **verificada** (realizado, com MMGD e revisões) estão no pipeline e na Silver, com horário UTC declarado pela fonte. Essa é a base para estudar o erro da previsão do operador e a carga líquida.
- **`cmo-semanal`** foi incluído (37 contratos ONS).
- **Backfill histórico** em `scripts/backfill.py`. Já foram executados os conjuntos pequenos e essenciais desde 2018 (EAR/ENA por subsistema, CMO semanal e semi-horário, balanço, curva de carga, carga diária).
- **CCEE/PLD bloqueado por firewall** (HTTP 403 para o IP de saída, inclusive no site principal). O conector está pronto e desligado em `configs/pipeline.json`. Até haver acesso, o CMO do ONS é a referência de preço disponível.
- A fonte devolve a área `SIN` da API de carga com valores zerados, por isso ela ficou fora da coleta (some os quatro subsistemas).

**Meteorologia por bacia e camada Gold (10/11/2026):**
- **ECMWF IFS Open Data** (sem cadastro, CC-BY-4.0) entrou no pipeline: chuva, temperatura e escoamento previstos até 15 dias, baixando só as variáveis por faixa de bytes.
- **Chuva média por bacia** (`scripts/basins.py`): os 31 polígonos do ONS, com 6 geometrias reparadas sem variação de área, e pesos pela área de cada célula da grade dentro do polígono (EPSG:5880).
- **Views no DuckDB** (`scripts/gold.py` → `data/gold/energia.duckdb`): chuva observada e prevista por bacia, chuva × ENA, carga prevista × verificada, carga líquida, EAR e CMO. Catálogo em [docs/gold_views.md](docs/gold_views.md).
- **Pesquisa** de fontes de fora e de modelos de países com matriz parecida (Noruega, Canadá, Nova Zelândia, Colômbia): [docs/research/meteorologia_bacias_e_modelos.md](docs/research/meteorologia_bacias_e_modelos.md).

**Meteorologia adquirida em 10/11/2026:** [relatório do lote](docs/inventory/weather_acquisition.md): sete dias MERGE, três horizontes GFS com vento a 100 m e ZIP INMET 2026 com 634 membros CSV. Os arquivos originais estão na Bronze. Foram identificadas seis geometrias inválidas nas 31 bacias ONS; veja os limites do cruzamento espacial no relatório.

## Entrega atual

- Inventário real dos **88 conjuntos ONS**, com **15.002 recursos** retornados na coleta inicial. O total inclui formatos alternativos, dicionários e eventuais recursos repetidos; não significa 15.002 séries independentes.
- Seleção inicial de **39 conjuntos**, configurável em configs/ons.json.
- Coletor de catálogo CKAN, downloader HTTP, auditoria SQLite e manifestos com hash.
- Oito amostras oficiais baixadas e verificadas, incluindo CSV/Parquet, EAR/ENA e shapefile ZIP de bacias.
- Comparador CSV/Parquet, perfilador CSV e testes de preservação de revisões/erros.
- Registro meteorológico separado e primeiro lote INPE/NOAA/INMET baixado e inspecionado; ampliações históricas e demais fontes permanecem pendentes.

Documentos: [arquitetura](docs/architecture.md), [fontes](docs/sources.md), [inventário completo](docs/inventory/ons_catalog.md), [recursos e URLs](docs/inventory/ons_resources.csv), [evidências de aquisição](docs/inventory/acquisition_validation.json).

Leia também os [achados das amostras](docs/inventory/findings.md): o balanço inclui o agregado SIN e as chaves EAR/ENA têm espaços à direita em alguns subsistemas. Esses problemas foram registrados sem alterar os dados.

Auditoria posterior: [endpoints recentes e datas efetivamente lidas](docs/inventory/endpoints_audit.md). Foram testadas 73 URLs de arquivos recentes em 39 conjuntos selecionados, todas HTTP 200; APIs de carga retornaram vazio no teste sem área e permanecem sem validação de observações. Isso amplia a evidência anterior de oito amostras, sem certificar todos os arquivos históricos.

## Execução no PowerShell

Use o .venv do projeto. O coletor principal requer apenas a biblioteca padrão; as dependências estão agrupadas para aquisição, meteorologia/geografia e desenvolvimento.

```powershell
# Instala todos os grupos do projeto atual (inclui os dois arquivos abaixo).
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# Confere importações e leitura/escrita Parquet, GRIB, NetCDF e geografia.
.\.venv\Scripts\python.exe scripts/check_environment.py
```

O verificador salva docs/environment.json e requirements-lock-windows.txt com as versões efetivamente instaladas. O lock é específico para o ambiente Windows/Python utilizado. Clientes CDS/ANA podem exigir credenciais próprias para acessar dados; a instalação não configura contas externas.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/acquire.py catalog --all-details
.\.venv\Scripts\python.exe scripts/inventory.py
```

O catálogo fica em data/catalog com uma cópia datada e um ponteiro latest.json. Para listar e baixar uma amostra:

```powershell
# Apenas mostra o plano; --limit é o total de arquivos, não por conjunto.
.\.venv\Scripts\python.exe scripts/acquire.py download --dataset balanco-energia-subsistema --format CSV --contains 2025
# Efetivamente baixa. Máximo padrão: 100 MB por arquivo.
.\.venv\Scripts\python.exe scripts/acquire.py download --dataset balanco-energia-subsistema --format CSV --contains 2025 --execute
.\.venv\Scripts\python.exe scripts/acquire.py download --dataset balanco-energia-subsistema --format PARQUET --contains 2025 --execute
.\.venv\Scripts\python.exe scripts/acquire.py download --dataset bacia_contorno --format ZIP --execute
# Dicionários são selecionados explicitamente.
.\.venv\Scripts\python.exe scripts/acquire.py download --dataset programacao_diaria --format JSON --documents --execute
```

O payload é guardado sem mudar bytes ou extensão lógica; o nome físico é o hash e o manifesto contém URL, formato e caminho. Consulte data/acquisition.sqlite e os arquivos *.manifest.json. Repetir uma coleta não duplica o objeto de conteúdo, mas registra uma nova tentativa. Mudanças da origem preservam ambos os objetos.

```powershell
# Repete exatamente as oito verificações limitadas da entrega.
.\.venv\Scripts\python.exe scripts/validate_sources.py
.\.venv\Scripts\python.exe scripts/inspect_samples.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
# Use os caminhos manifest.path do relatório (não URLs) nos comandos abaixo.
.\.venv\Scripts\python.exe scripts/acquire.py profile-csv CAMINHO_CSV --key id_subsistema --key din_instante
.\.venv\Scripts\python.exe scripts/compare_formats.py CAMINHO_CSV CAMINHO_PARQUET --output data/reports/comparison.json
```

API de carga: primeiro obter o código oficial da área e conferir a documentação. Comando disponível, ainda não validado com observações reais:

```powershell
.\.venv\Scripts\python.exe scripts/acquire.py ons-load --kind programada --date 2025-01-01 --area CODIGO_OFICIAL
```

O comando consulta um dia por chamada. Inspecionar erro, paginação e completude do JSON antes de automatizar. Não existe comparação automática API/CSV pois os produtos têm granularidades e componentes diferentes.

Meteorologia: cadastros em configs/meteorology.json. Dependências espaciais e meteorológicas em requirements-research.txt (apesar do nome, são ferramentas de inspeção de dados), incluídas na instalação completa por requirements-dev.txt.

```powershell
# Inspeciona colunas/CRS do shapefile. Usar caminho absoluto prefixado por zip://.
.\.venv\Scripts\python.exe scripts/plan_weather.py zip://CAMINHO_ABSOLUTO_ZIP
# Depois de identificar a coluna de bacia correta:
.\.venv\Scripts\python.exe scripts/plan_weather.py zip://CAMINHO_ABSOLUTO_ZIP --id-column COLUNA_OFICIAL
# GFS: substitua os marcadores pela rodada disponível e retângulo de uma bacia.
# Por padrão só imprime a URL; acrescente --execute para baixar.
.\.venv\Scripts\python.exe scripts/acquire.py gfs --date AAAA-MM-DD --cycle 0 --lead 24 --bbox OESTE SUL LESTE NORTE
```

O primeiro download GFS foi validado ao vivo. A inspeção espacial encontrou seis geometrias inválidas no arquivo ONS: plan_weather.py rejeita um conjunto assim, enquanto discover_weather.py registra o problema e download_weather.py usa apenas o retângulo envolvente para aquisição. Máscara e pesos por interseção são entregáveis futuros. Em eólica/solar usar parques/conjuntos, sem presumir o mesmo recorte hidrológico.

## Ordem dos próximos marcos

1. ~~Validar carga via API~~ (feito em 10/11/2026) e ~~dimensionar histórico~~ (`docs/inventory/backfill_plan.md`). Executar o backfill completo (~1,5 GB) e conferir cobertura e lacunas por ano.
2. Obter acesso à CCEE (PLD horário/semanal) por outra rede ou pedido de liberação; então observar o schema e escrever o adaptador Silver.
3. Confirmar o fuso horário dos produtos ONS em arquivo (só a API de carga tem UTC declarado) antes de junções temporais com meteorologia.
4. Resolver a interpretação das seis geometrias inválidas e a correspondência bacia–reservatório–usina; calcular a chuva média por bacia (pesos por área).
5. Histórico meteorológico: MERGE por backfill; previsões e reanálise via ERA5/CDS (conta própria). Depois, produtos Gold (carga líquida, balanço por subsistema) e a fase de modelagem.

Sem modelos matemáticos ou backtest nesta entrega. main.py original do PyCharm foi preservado.
