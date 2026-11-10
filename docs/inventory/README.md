# Evidências de fontes e arquivos

| Arquivo | Como interpretar |
|---|---|
| ons_catalog.md | Descrições e seleção de todos os conjuntos inventariados |
| ons_resources.csv | Recursos, formatos e URLs recebidos do catálogo |
| acquisition_validation.json | Oito downloads limitados e suas verificações |
| sample_coverage.json | Cobertura e grupos duplicados nas amostras CSV |
| csv_parquet_comparison.json | Diferenças de registros e schemas entre formatos |
| endpoints_audit.json | Detalhes das URLs recentes e datas internas lidas |
| endpoints_audit.md | Resumo legível dessa auditoria |
| load_api_probe.json | Respostas do teste pontual das APIs de carga |
| findings.md | Achados da aquisição inicial e seu escopo |
| weather_discovery.json | Listagens oficiais e inspeção dos polígonos de bacias |
| weather_acquisition.json | Manifestos e metadados internos do lote INPE/NOAA/INMET |
| weather_acquisition.md | Resumo legível do lote e seus limites |
| weather_summary.json | Arquivos, tamanhos, hashes e geometrias inválidas |
| pipeline_status.md / pipeline_status.json | Estado da última execução e contagens de snapshots Silver |
| windows_task.json | Configuração da tarefa Windows e resultado do disparo de teste |

Os arquivos JSON são evidências para auditoria, não tabelas Gold. Um HTTP 200 comprova resposta; uma data máxima recente comprova presença daquela referência, mas não a completude de todas as entidades/períodos.
