# Pipeline diário de aquisição e tratamento

O fluxo agora tem execução única em `scripts/pipeline.py`: coleta e preservação Bronze → tratamento Silver → publicação de snapshots aprovados e relatórios. Gold e modelos estatísticos continuam em uma fase posterior.

## Frequências e publicação

O Agendador chama o programa a cada 15 minutos. O programa decide quais fontes estão devidas, com pequena folga de relógio para não perder um disparo por diferença de segundos.

| Fonte/produto | Política de consulta | Evidência sobre publicação |
|---|---|---|
| ONS hidráulica horária | Cada tick de 15 minutos | ONS declara atualização a cada 15 min |
| Demais 36 contratos ONS (inclui `cmo-semanal`) | Aproximadamente a cada hora | Horários diferentes por produto; sem presumir um horário único |
| Carga **programada** (API, previsão do ONS) | A cada hora, D e D+1, por subsistema SECO/S/NE/N | D+1 já aparece no dia anterior; resposta vazia de D+1 é tratada como "ainda não publicado" |
| Carga **verificada** (API, realizado + MMGD) | A cada 6 h, últimos 7 dias | Sai ~03h UTC do dia seguinte e é **revisada** depois (`din_atualizacao`); cada revisão vira novo objeto na Bronze |
| CCEE (PLD) | Desligado (`ccee.enabled=false`) | Firewall da CCEE devolveu 403 para o IP de saída; conector pronto para quando o acesso for liberado |
| MERGE diário | A cada hora, rechecando últimos três dias | Arquivo é descoberto no diretório oficial, não inferido pelo relógio |
| GFS | A cada hora, verificando ciclos 00/06/12/18 UTC e horizontes 24/48/72 h | Um ciclo só é coletado quando o arquivo é anunciado; não presumir publicação na hora da rodada |
| ECMWF IFS Open Data | A cada hora, rodada 00z, horizontes 24–360 h (chuva, temperatura a 2 m, escoamento) | Índice `.index` informa as mensagens; download só das variáveis por faixa de bytes. Origem guarda só ~12 rodadas |
| Gold (médias por bacia + views DuckDB) | Ao fim de toda execução com Silver nova | `scripts/gold.py`; ver [gold_views.md](gold_views.md) |
| INMET ZIP anual | Consulta diária | O produto é consolidado; uma consulta diária não gera observações novas diariamente |

ONS diário declara atualizações às 9h15, 14h15 e 17h. A consulta horária é uma escolha inicial do projeto, e não garantia de captura imediata nesses minutos. A política pode ser afinada em configs/pipeline.json.

Fontes: [ONS horário](https://dados.ons.org.br/dataset/dados_hidrologicos_ho), [ONS diário](https://dados.ons.org.br/dataset/dados-hidrologicos-res), [NOAA NOMADS](https://nomads.ncep.noaa.gov/), [INMET histórico](https://portal.inmet.gov.br/dadoshistoricos).

## Comandos

```powershell
# Trata tudo que já tem adaptador na Bronze, sem rede.
.\.venv\Scripts\python.exe scripts/pipeline.py --offline
# Atualiza fontes devidas e trata conteúdo novo.
.\.venv\Scripts\python.exe scripts/pipeline.py
# Reconsulta agora todas as tarefas, mantendo cache de arquivos sem alteração.
.\.venv\Scripts\python.exe scripts/pipeline.py --force
# Executa somente um grupo quando ele está devido.
.\.venv\Scripts\python.exe scripts/pipeline.py --tasks ons
.\.venv\Scripts\python.exe scripts/status_pipeline.py
```

O job é protegido por trava de processo. Só há uma execução por vez; o próprio Windows também é configurado para ignorar disparos sobrepostos. Se a trava estiver ocupada, a execução nova registra isso no log e sai com 0 (não é falha). Uma falha não transforma a execução em sucesso: o relatório fica `partial`, o processo retorna 1 e fontes independentes continuam sendo tentadas. Erros inesperados também geram relatório `partial` em vez de sumir sem rastro.

`status_pipeline.py` acusa `attention` quando o último relatório está atrasado (mais de dois ticks) ou quando o Agendador registrou código diferente de 0. Isso pega execuções que caem no meio e por isso não gravam relatório.

## Histórico (backfill)

O pipeline diário olha só os últimos dias. Para modelos e backtests use `scripts/backfill.py`, que **planeja por padrão** e só baixa com `--execute`:

```powershell
# Plano (nada é baixado): grava docs/inventory/backfill_plan.md com arquivos e tamanhos
.\.venv\Scripts\python.exe scripts/backfill.py --sources ons,load --start 2018-01-01
# Executa o plano (recusa acima de --max-gb, padrão 10)
.\.venv\Scripts\python.exe scripts/backfill.py --sources ons,load --start 2018-01-01 --execute
# Chuva MERGE de um período explícito
.\.venv\Scripts\python.exe scripts/backfill.py --sources merge --start 2025-01-01 --end 2025-12-31
```

- Usa trava própria (`data/backfill.lock`): o agendamento diário continua rodando em paralelo.
- API de carga em blocos mensais por área (≈100× menos chamadas que dia a dia).
- Relatório em `data/runs/backfill_<run_id>.json`; não sobrescreve `runs/latest.json`.
- GFS não tem histórico no NOMADS (~10 dias). Histórico de previsão/reanálise exige ERA5/CDS (conta própria).
- Na carga, janelas diárias e mensais podem se sobrepor no índice: deduplicar por `(cod_areacarga, din_referenciautc)` mantendo o maior `source_updated_at_utc`/`_available_at_utc`.

`--force` ignora a cadência; não ignora testes de qualidade. `--offline` não atualiza o estado de consulta das fontes. O script histórico `build_contracts.py` gera os 36 contratos iniciais do schema auditado; não deve ser executado automaticamente a cada dia para aceitar alterações desconhecidas de schema.

## O tratamento implementado

### ONS

- Confere presença das colunas esperadas e registra colunas novas.
- Remove espaços nas strings, incluindo códigos `N ` e `S `.
- Tipos numéricos definidos por contrato, com conversão de vírgula decimal.
- Mantém `val_tipoperda` como categoria, apesar do nome começar por `val_`.
- Remove apenas duplicatas de linha inteira, inclusive após a normalização; não escolhe arbitrariamente entre valores conflitantes da mesma chave.
- Identifica agregado SIN sem somá-lo às quatro regiões.
- Valores não interpretáveis e códigos desconhecidos vão à quarentena.
- EAR acima de 100 é sinalizado em `_quality_warnings`, preservando seu valor: há exemplos assim na origem e a referência nominal pode ser ultrapassada. Não é truncado em 100.
- ENA percentual da MLT pode superar 100 normalmente.

Horários ONS ainda ficam em `_event_time_source`, sem converter para UTC quando a convenção específica não foi confirmada. `_timezone_status` explicita essa pendência. O dado não está pronto para uma junção temporal UTC rigorosa sem completar esse contrato.

### API de carga ONS (programada e verificada)

- Únicos dados ONS do projeto com **fuso declarado**: o dicionário oficial diz que `din_referenciautc` está em UTC e marca o **fim** da meia hora. A Silver cria `interval_end_utc` e `interval_start_utc` (= fim − 30 min).
- `dat_referencia` é a data operativa brasileira; por isso o "hoje" da coleta usa UTC−3.
- Verificada traz `val_cargammgd` (micro e minigeração distribuída) e `val_cargaglobalsmmgd` (carga sem MMGD): é a fonte da "carga líquida" citada na pesquisa.
- `source_updated_at_utc` vem de `din_atualizacao` e permite escolher a revisão mais recente.
- Mesma área e intervalo repetidos na mesma resposta vão à quarentena (`duplicate_key`).
- Carga total zero recebe alerta `zero_total_load`, sem apagar. A área `SIN` da API devolve só zeros (verificado em 2025-10 e 2026-11) e ficou fora da coleta: some SECO+S+NE+N.

### GRIB MERGE/GFS

- Converte mensagens em tabela longa com variável, valor, unidade, latitude e longitude.
- Kelvin → Celsius; kg/m² de água → mm; preserva pressão em Pa e radiação em W/m².
- Mantém níveis do vento separados e não calcula geração de energia.
- Preserva rodada, validade e `startStep/endStep`; intervalos diferentes de chuva não são somados entre si.
- MERGE é interpretado pelo CTL (PREC/NEST); o rótulo genérico do leitor não altera sua definição.
- Não inventa uma janela diária do MERGE: marca `closure_unverified` até confirmar o fechamento.
- Recorta apenas por retângulo das bacias. Não há média por polígono nem reparo das seis geometrias inválidas.

### INMET

- Lê cada membro CSV do ZIP separadamente para limitar memória.
- Normaliza nomes de colunas, decimais e horários explicitamente rotulados UTC.
- `-9999` vira null; ausência não vira zero nem é interpolada.
- Preserva campos de radiação acumulada em kJ/m², sem confundi-los com fluxo W/m².
- Conta ausências por campo/estação e mantém rastreabilidade até o membro ZIP.

## Publicação e histórico

```text
data/
  bronze/                         originais e manifestos, sem alterações
  silver/<fonte>/<dataset>/<recurso>/<versão>/<hash>/
    *.valid.parquet               registros aprovados
    *.quarantine.parquet          registros rejeitados e motivos
    snapshot.json                 marcador de publicação e qualidade
  silver/current.json             índice dos snapshots atuais aprovados
  pipeline.sqlite                 última consulta por tarefa e estado dos recursos
  runs/<run_id>.json              relatório de cada execução concluída
  runs/latest.json                última execução
  runs/pipeline.log               log Python
  runs/scheduler.log              saída do agendamento Windows
```

**Onde os dados ficam fisicamente:** nesta máquina, `data/` é um *junction* do Windows que aponta para `D:\EnergyData\data`, criado em 10/11/2026 porque o disco C estava quase cheio. O código continua usando `data/` normalmente, e caminhos antigos gravados nos manifestos (`C:\...\Energy\data\...`) continuam válidos. Para recriar em outra máquina:

```powershell
robocopy .\data D:\EnergyData\data /E /COPY:DAT /DCOPY:DAT   # copiar
Rename-Item data data_old; cmd /c mklink /J data D:\EnergyData\data   # trocar pelo junction
```

Quem clonar o repositório não precisa disso: `data/` está no `.gitignore` e é criada na primeira execução.

Não leia `data/silver/**/*.parquet` como tabela única: isso mistura histórico, versões, fontes e quarentena. Use o índice current.json e selecione os arquivos `.valid.parquet` do conjunto pretendido. CSV e Parquet do mesmo arquivo ONS compartilham um slot de publicação; ele não deve ser contado duas vezes.

Cada snapshot tem hash da origem, identificador do recurso e `_available_at_utc`, que é a primeira coleta comprovada daquele conteúdo neste ambiente. Isso não reconstrói a disponibilidade histórica anterior ao início da coleta. O índice mantém o último snapshot aprovado se a versão nova falhar.

A versão da transformação depende de contratos, limite de qualidade e código silver.py (frequências e notas da configuração não reprocessam a Silver). O mesmo input/versão é reutilizado quando seu marcador de publicação e arquivos existem. Alterações da fonte preservam novas versões na Bronze; ETag/Last-Modified evitam downloads repetidos. Arquivos sem validador HTTP são baixados para conferir os bytes.

O limite padrão de rejeição é 1% do arquivo. Acima disso, o snapshot fica `quality_failed` e não substitui o último aprovado. As regras são explícitas; não se muda o limite apenas para esconder falhas da fonte. Não há exclusão automática de histórico nesta primeira versão: acompanhar o uso de disco é necessário antes de ampliar períodos e frequência.

## Agendamento Windows

```powershell
# Instala/atualiza somente a tarefa deste projeto.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_pipeline_task.ps1
Get-ScheduledTask -TaskName Energy-Data-Pipeline
Get-ScheduledTaskInfo -TaskName Energy-Data-Pipeline
# Remove somente esta tarefa, mantendo todos os dados.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_pipeline_task.ps1 -Uninstall
```

A tarefa usa a conta atual, sem senha armazenada e sem privilégios administrativos. Executa em janela oculta, ao iniciar sessão e em intervalos de 15 min. **O computador precisa estar ligado, com a sessão do usuário iniciada e acesso à internet.** Não é hospedagem 24/7. Iniciar quando disponível recupera disparos perdidos; a consulta retroativa curta recupera parte das publicações tardias, sem reconstruir automaticamente todo o período de uma longa interrupção.

O wrapper `run_pipeline.ps1` redireciona a saída pelo `cmd.exe`. No PowerShell 5.1, redirecionar o stderr de um executável com `ErrorActionPreference=Stop` transformava a primeira linha de log em exceção e matava o Python no meio da execução (corrigido em 10/11/2026).

O job cobre 37 produtos ONS tabulares, as duas APIs de carga (SECO/S/NE/N) e MERGE/GFS/INMET. Continuam bloqueados: CCEE/PLD (403 de firewall) e ERA5/ECMWF/GEFS/ANA (conectores não implementados); ver `blocked_sources` em configs/pipeline.json.
