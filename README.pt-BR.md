# Energy: pipeline de dados do setor elétrico brasileiro

Pipeline de dados e modelos inspirado no que mesas de comercialização de energia usam para acompanhar o sistema elétrico. Ele coleta dados **oficiais do ONS** (arquivos CSV/Parquet do portal **e** APIs) e **meteorologia** (observada e prevista), organiza tudo em camadas **Bronze → Silver → Gold** e termina numa **previsão diária da carga líquida** (carga − eólica − solar) para amanhã e depois de amanhã, comparada com a programação do próprio ONS.

> Projeto pessoal de estudo e portfólio. **Resultados em uma página: [docs/resultados.md](docs/resultados.md).** · [English](README.md)

| Previsão (backtest, confirmação em 2026) | Régua | Ganho de MAE |
|---|---|---|
| Carga líquida D+1, SIN horário | Programação DESSEM do ONS | **11,2%** |
| Carga líquida D+2, antes de existir programação | Programação de T−1 corrigida por hora e dia da semana | **25,9%** |
| ENA por bacia, 1 dia | Persistência | 30,5% |

## A pergunta de negócio

No Brasil, o preço de curto prazo (CMO/PLD) depende de **quanta água vai chegar aos reservatórios** e de **quanta carga o sistema vai atender**. Duas coisas antecipam esse preço:

1. **O erro da previsão de carga do operador**: a carga programada pelo ONS comparada com a carga verificada.
2. **A chuva dentro das bacias**, observada e prevista, que antecede a ENA (energia natural afluente) e a EAR (energia armazenada).

O pipeline existe para que essas perguntas possam ser respondidas com dados rastreáveis.

## Arquitetura

```mermaid
flowchart LR
    subgraph Fontes
        A[ONS CKAN<br/>CSV/Parquet] --> B
        A2[ONS API de carga<br/>programada × verificada] --> B
        M[MERGE/CPTEC<br/>chuva observada] --> B
        E[ECMWF Open Data<br/>previsão 15 dias] --> B
        G[GFS/NOAA] --> B
        I[INMET estações] --> B
    end
    B[Bronze<br/>bytes originais + hash + manifesto] --> S[Silver<br/>tipado, validado, quarentena]
    S --> P[Média por bacia<br/>pesos por área, 31 polígonos ONS]
    S --> V[(Gold: DuckDB views)]
    P --> V
    O[Open-Meteo<br/>previsões arquivadas e atuais] --> MD
    V --> MD[models/<br/>Ridge por hora, GBM, correção de viés]
    MD --> BT[Backtests walk-forward<br/>escolha 2025, confirmação 2026]
    MD --> PO[Previsão operacional<br/>D+1 e D+2 com banda de 80%]
    BT --> BI[Power BI<br/>PBIP + TMDL, modelo estrela]
    PO --> BI
```

| Camada | O que garante |
|---|---|
| **Bronze** | Bytes exatamente como recebidos, endereçados por SHA-256. Cada revisão da fonte é preservada, e cada tentativa fica registrada em SQLite |
| **Silver** | Contrato de schema por conjunto, tipos, chaves normalizadas, linhas inválidas em quarentena (nunca corrigidas em silêncio), linhagem até o arquivo de origem e versão da transformação |
| **Gold** | Médias meteorológicas por bacia e views de negócio no DuckDB (sem cópia de dados) |
| **Modelos** | Só usam o que existia na hora da decisão (testes de vazamento), com dados tratados antes (solar noturna, valores congelados, DESSEM incompleto) |

## Fontes

| Fonte | Conteúdo | Frequência no pipeline |
|---|---|---|
| ONS (portal CKAN) | 37 conjuntos: balanço, geração, EAR/ENA por bacia/REE/subsistema, CMO, intercâmbio, restrições eólica/solar… | Horária (hidrologia: 15 min) |
| ONS (API `apicarga`) | Carga **programada** (D, D+1) e **verificada** com MMGD, por subsistema, em UTC | Horária / 6 h |
| MERGE/CPTEC | Chuva diária observada, 0,1° | Horária (últimos 3 dias) |
| ECMWF IFS Open Data | Chuva, temperatura e escoamento previstos, até 15 dias | Diária (rodada 00z) |
| GFS/NOAA | Previsão 24/48/72 h | Horária |
| INMET | Estações automáticas | Diária |
| Open-Meteo | Previsões **arquivadas como emitidas** (GFS e ECMWF, 48/72/96 h antes) e previsão atual, nos pontos das usinas e capitais. CC-BY 4.0, uso não comercial | Sob demanda (backtest e previsão diária) |
| CCEE (PLD) | Conector pronto e desligado: o firewall da CCEE bloqueia o IP de saída (HTTP 403) | — |

Detalhes, decisões e limitações de cada fonte: [docs/sources.md](docs/sources.md), [docs/pipeline_diario.md](docs/pipeline_diario.md) e a [pesquisa de fontes e modelos](docs/research/meteorologia_bacias_e_modelos.md).

## Primeiros resultados (das views Gold)

- **Previsão de carga do ONS (2021–2026):** o erro percentual médio absoluto da carga programada contra a verificada fica entre **2,6% e 4,4%** ao ano (2022 foi o pior ano, 2024 o melhor). A carga programada da API começa em 2021.
- **Chuva × ENA (2018–2026, 3.235 dias):** a chuva acumulada em 15 dias por bacia correlaciona com a ENA de 7 dias depois em **0,8 no Grande, 0,78 no Tocantins e 0,77 no Paranaíba**, mas só **0,3 a 0,4 no Uruguai e no Jacuí**. As bacias do Sul respondem rápido e não têm estação seca marcada. Parte da correlação alta é sazonalidade. A vantagem real só aparece comparando com a previsão do próprio ONS, o que fica para a fase de modelagem.

## Como rodar

```powershell
# 1. Ambiente (Windows, Python 3.13)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# 2. Coleta incremental: Bronze → Silver → Gold
.\.venv\Scripts\python.exe scripts/pipeline.py

# 3. Histórico (por padrão só PLANEJA e mostra o tamanho; --execute baixa)
.\.venv\Scripts\python.exe scripts/backfill.py --sources ons,load --start 2018-01-01

# 4. Consultar as views
.\.venv\Scripts\python.exe -c "import duckdb; c=duckdb.connect('data/gold/energia.duckdb', read_only=True); print(c.sql('FROM vw_carga_prevista_vs_verificada LIMIT 5'))"

# 5. Previsão da carga líquida de amanhã e depois de amanhã (ideal após as 20h de Brasília)
.\.venv\Scripts\python.exe scripts/prever_carga_liquida.py

# 6. BI: tabelas em modelo estrela e projeto Power BI (abrir bi/Energia.pbip e clicar em Atualizar)
.\.venv\Scripts\python.exe scripts/exportar_bi.py
.\.venv\Scripts\python.exe scripts/gerar_projeto_bi.py

# 7. Refazer os backtests (D+1 e D+2)
.\.venv\Scripts\python.exe scripts/carga_liquida_d1.py
.\.venv\Scripts\python.exe scripts/carga_liquida_d1.py --horizonte 2

# 8. Estado e testes
.\.venv\Scripts\python.exe scripts/status_pipeline.py
.\.venv\Scripts\python.exe -m pytest -q tests
```

- **Agendamento:** `scripts/install_pipeline_task.ps1` registra uma tarefa no Agendador do Windows (a cada 15 min; cada fonte tem a própria cadência).
- **Dados em outro disco:** defina `ENERGY_DATA_DIR`, ou use um junction em `data/`.
- **Comandos avulsos:** [docs/comandos_manuais.md](docs/comandos_manuais.md).

## Estrutura

```
configs/            contratos de schema, políticas de coleta, correspondência de bacias
scripts/            pipeline: acquire, pipeline, silver, basins, gold, backfill, status; backtests e previsão
models/             leitura da Gold, tratamento, modelos (carga, renováveis, ENA), validação e operação
scripts/preparacao/ geraram inventários e contratos (rodar só se a fonte mudar)
scripts/diagnostico/ auditorias e investigações pontuais
tests/              testes sem rede (pytest)
bi/                 projeto Power BI em texto (PBIP + TMDL) e roteiro das páginas
docs/               arquitetura, fontes, views, pesquisa, guia de estudo, inventários
data/               (fora do git) bronze/ silver/ gold/ runs/
```

## Decisões de engenharia que valem destacar

- **Idempotência por conteúdo:** HEAD/ETag evita downloads repetidos, e o hash evita objetos duplicados. A Silver é reaproveitada enquanto a entrada e a versão forem as mesmas.
- **Versão da transformação:** muda quando muda o contrato, o limite de qualidade ou o código do `silver.py`. Mudar frequência de coleta não reprocessa nada.
- **Nada de fuso inventado:** só a API de carga e a meteorologia têm UTC declarado. Os demais horários ficam "como publicados", marcados como não verificados.
- **Média por bacia correta:** a área de cada célula dentro do polígono é calculada em projeção de área (EPSG:5880). Células sem dado não viram zero, e cada valor vem com a fração da bacia coberta.
- **Revisões e backtest:** a carga verificada é revisada pelo ONS e cada revisão vira um objeto novo. As previsões são guardadas por rodada, para permitir simular "o que se sabia no dia".
- **Falhas visíveis:** uma fonte que falha não derruba as outras. A execução fica `partial` e o status alerta quando o agendamento para.

- **Sem vazamento por construção:** cada variável usa só o que existia às 22h da véspera (verificado até D−1, previsão do tempo emitida 48 h ou 72 h antes). Testes alteram o futuro e conferem que nada muda.
- **Régua justa antes de comemorar:** todo modelo é comparado com a referência que uma mesa já teria de graça (ONS corrigido pelo viés, ou por dia da semana em D+2). Um primeiro "ganho de 42%" em D+2 caiu para 26% com a régua certa.

## Modelos e resultados

- [docs/resultados.md](docs/resultados.md): resumo, limitações e próximo passo.
- [bi/README.md](bi/README.md): BI no Power BI (modelo estrela, medidas DAX, roteiro das páginas).
- Pesquisa detalhada:
  - [carga líquida D+1](docs/research/carga_liquida_d1.md);
  - [carga líquida D+2](docs/research/carga_liquida_d2.md);
  - [carga D+1](docs/research/carga_d1.md);
  - [ENA e carga diária](docs/research/modelagem_meteorologia_energia.md);
  - [solar e sazonalidade](docs/research/solar_e_sazonalidade.md).

**Próximo passo:** ligar a carga líquida prevista de D+2 ao preço estimado (CMO/PLD) e medir se ela antecipa o movimento do preço.

---
Para estudar o código linha a linha: [docs/guia_de_estudo.md](docs/guia_de_estudo.md) · mapa dos scripts: [scripts/README.md](scripts/README.md) · consultas SQL: [docs/sql_do_projeto.md](docs/sql_do_projeto.md).

*Dados: ONS (dados abertos), CPTEC/INPE (MERGE), NOAA (GFS), INMET e ECMWF Open Data (CC-BY-4.0).*
