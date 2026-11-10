# Programas Python

Todos têm comentários em português no próprio código. O [guia de estudo](../docs/guia_de_estudo.md) sugere a ordem de leitura.

| Arquivo | Entrada | Saída e efeito |
|---|---|---|
| acquire.py | Opções CLI, config e/ou catálogo | Descobre fontes, baixa para Bronze ou inspeciona CSV; rede depende do comando |
| inventory.py | Catálogo local e seleção ONS | Reescreve inventário CSV/Markdown, sem rede |
| validate_sources.py | Catálogo local | Baixa oito amostras e reescreve relatório de validação |
| inspect_samples.py | Manifestos das amostras | Reescreve cobertura temporal/duplicatas, sem rede |
| compare_formats.py | CSV e Parquet locais | Compara registros e pode gravar JSON, sem rede |
| audit_endpoints.py | Seleção de conjuntos | Faz HEAD/GET e reescreve arquivos e relatórios da auditoria |
| probe_load_api.py | Endpoints e data fixa no código | Teste pontual das APIs, usa rede e reescreve resultados |
| summarize_audit.py | Resultados anteriores da auditoria | Reinterpreta datas e reescreve o relatório, sem rede |
| plan_weather.py | Arquivo geográfico e coluna ID opcional | Inspeciona geometrias ou publica retângulos, sem baixar meteorologia |
| check_environment.py | Bibliotecas instaladas | Faz testes locais temporários e salva versões/relatório |
| discover_weather.py | Polígonos ONS e diretórios oficiais | Inspeciona bacias e preserva listagens de arquivos, com rede |
| download_weather.py | Descoberta meteorológica | Baixa primeiro lote MERGE/GFS/INMET na Bronze e inspeciona metadados |
| report_weather.py | Lote meteorológico local e manual PDF | Publica evidências, campos encontrados e limitações; sem rede |
| build_contracts.py | Schemas auditados | Gera os contratos iniciais; revisão manual em mudanças de fonte |
| pipeline.py | Políticas, contratos e fontes vivas | Coleta incremental, tratamento e publicação Silver; --offline evita rede |
| silver.py | Bytes da Bronze e contrato | Funções de tratamento, quarentena e publicação; é importado pelo pipeline |
| status_pipeline.py | Estado local, snapshots e Agendador | Gera relatório de situação e alertas (relatório atrasado, código do Agendador), sem rede |
| basins.py | Polígonos ONS e grade meteorológica | Repara geometrias, calcula pesos por área e médias por bacia; importado pela Gold |
| gold.py | Snapshots Silver atuais | Gera médias por bacia (data/gold/basin_weather) e recria as views em data/gold/energia.duckdb |
| backfill.py | Período, fontes (ons/load/merge) | Planeja histórico com tamanhos; com --execute baixa e trata usando o mesmo código do pipeline |
| inspect_rejections.py | Quarentenas anteriores | Mostra os motivos das rejeições para investigação |

`run_pipeline.ps1` é o wrapper do agendamento, e `install_pipeline_task.ps1` instala/remove a tarefa Windows. Veja o [guia operacional](../docs/pipeline_diario.md).

Em acquire.py, leia nesta ordem: helpers pequenos → classe Store → discover/resource_plan → profile_csv/gfs_url → main. A função main é maior porque configura e encaminha todos os subcomandos.

Os scripts trocam dados por arquivos e por importação de funções. `from acquire import Store` significa reutilizar a classe existente; não inicia automaticamente um download.
