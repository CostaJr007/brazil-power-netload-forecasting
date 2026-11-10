# Comandos manuais (fora do pipeline diário)

O pipeline diário (`scripts/pipeline.py`) e o backfill (`scripts/backfill.py`) cobrem a operação normal. Os comandos abaixo servem para explorar, auditar ou baixar algo pontualmente. Todos rodam no PowerShell, na raiz do projeto, com o `.venv`.

## Ambiente

```powershell
# Instala todos os grupos (requirements-dev inclui research, que inclui requirements.txt).
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# Confere importações e leitura/escrita de Parquet, GRIB, NetCDF e geografia.
.\.venv\Scripts\python.exe scripts/diagnostico/check_environment.py
```

O verificador salva `docs/environment.json` e `requirements-lock-windows.txt` com as versões instaladas (o lock vale para este ambiente Windows/Python). Clientes CDS/ANA exigem credenciais próprias, que a instalação não configura.

## Catálogo ONS e downloads pontuais

```powershell
.\.venv\Scripts\python.exe scripts/acquire.py catalog --all-details
.\.venv\Scripts\python.exe scripts/preparacao/inventory.py
# Só mostra o plano; --limit é o total de arquivos, não por conjunto.
.\.venv\Scripts\python.exe scripts/acquire.py download --dataset balanco-energia-subsistema --format CSV --contains 2025
# Baixa de fato (máximo padrão: 100 MB por arquivo).
.\.venv\Scripts\python.exe scripts/acquire.py download --dataset balanco-energia-subsistema --format PARQUET --contains 2025 --execute
.\.venv\Scripts\python.exe scripts/acquire.py download --dataset bacia_contorno --format ZIP --execute
# Dicionários de dados são selecionados explicitamente.
.\.venv\Scripts\python.exe scripts/acquire.py download --dataset programacao_diaria --format JSON --documents --execute
```

O conteúdo é guardado sem alterar bytes. O nome físico é o hash SHA-256, e o manifesto registra URL, formato e caminho. Repetir uma coleta não duplica o objeto, mas registra a nova tentativa em `data/acquisition.sqlite`. Revisões da fonte preservam as duas versões.

## Auditoria e comparação

```powershell
.\.venv\Scripts\python.exe scripts/diagnostico/validate_sources.py
.\.venv\Scripts\python.exe scripts/diagnostico/inspect_samples.py
# Use caminhos manifest.path (não URLs).
.\.venv\Scripts\python.exe scripts/acquire.py profile-csv CAMINHO_CSV --key id_subsistema --key din_instante
.\.venv\Scripts\python.exe scripts/diagnostico/compare_formats.py CAMINHO_CSV CAMINHO_PARQUET --output data/reports/comparison.json
```

## API de carga (consulta avulsa)

Códigos de área confirmados: `SECO`, `S`, `NE`, `N` (a área `SIN` devolve zeros). O pipeline já coleta essa API todo dia. Para uma consulta isolada:

```powershell
.\.venv\Scripts\python.exe scripts/acquire.py ons-load --kind programada --date 2025-01-01 --area SECO
```

## Meteorologia e geografia

```powershell
# Inspeciona colunas/CRS do shapefile (caminho absoluto com prefixo zip://).
.\.venv\Scripts\python.exe scripts/preparacao/plan_weather.py zip://CAMINHO_ABSOLUTO_ZIP --id-column ID
# GFS avulso: por padrão só imprime a URL; --execute baixa.
.\.venv\Scripts\python.exe scripts/acquire.py gfs --date AAAA-MM-DD --cycle 0 --lead 24 --bbox OESTE SUL LESTE NORTE
```

Para eólica e solar, use as localizações de parques e conjuntos, não o recorte das bacias hidrográficas.
