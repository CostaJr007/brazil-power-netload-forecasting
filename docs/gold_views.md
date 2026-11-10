# Camada Gold e views (DuckDB)

`scripts/gold.py` recria `data/gold/energia.duckdb` a cada coleta com Silver nova. O banco contém **apenas views**, sem cópia de dados: elas leem os Parquets atuais da Silver e da Gold.

```powershell
.\.venv\Scripts\python.exe scripts/gold.py      # atualiza manualmente
.\.venv\Scripts\python.exe -c "import duckdb; c=duckdb.connect('data/gold/energia.duckdb', read_only=True); print(c.sql('SHOW TABLES'))"
```

Para usar no PyCharm (Database → DuckDB), abra o arquivo **somente leitura**. Uma conexão de escrita aberta impede o pipeline de substituir o banco; nesse caso a coleta registra o erro `gold` e segue.

## Views de base
| View | Conteúdo |
|---|---|
| `silver_<conjunto>` | Os `.valid.parquet` atuais de cada conjunto Silver (ex.: `silver_ena_diario_por_bacia`) |
| `gold_basin_weather` | Média por bacia de cada snapshot meteorológico (MERGE, GFS, ECMWF): `value`, `coverage`, intervalos e rodada |
| `basins` | 31 bacias: área em km² e se a geometria foi reparada |
| `basin_ena_mapping` | Polígono ↔ `nom_bacia` da ENA e o tipo de correspondência |

## Views de negócio
| View | Grão | Uso |
|---|---|---|
| `vw_chuva_observada_bacia_diaria` | bacia × dia | Chuva MERGE por bacia, ponderada por área, com `cobertura_area` |
| `vw_previsao_chuva_bacia` | modelo × bacia × rodada × horizonte | Chuva prevista por período (diferença de acumulados), ECMWF e GFS |
| `vw_ena_bacia_diaria` | bacia ONS × dia | ENA bruta (MWmed e % MLT) e armazenável |
| `vw_chuva_x_ena_bacia` | bacia × dia | **Tabela da hipótese**: chuva observada × ENA |
| `vw_carga_prevista_vs_verificada` | subsistema × meia hora (UTC) | Previsão do ONS × realizado, MMGD e erro da previsão |
| `vw_balanco_carga_liquida` | subsistema × hora | Carga, eólica, solar, hidráulica, térmica e carga líquida (sem o agregado SIN) |
| `vw_ear_subsistema_diaria` | subsistema × dia | EAR em % e MWmês |
| `vw_cmo_semanal` | subsistema × semana | CMO médio e por patamar |

## Regras e cuidados
- **Fuso horário:** só a API de carga (`*_utc`) e a meteorologia têm UTC declarado. As colunas `instante_fonte` e `data_referencia` dos arquivos ONS ficam como publicadas.
- **Média por bacia:** `Σ(valor × área da célula dentro da bacia) / Σ(área com valor)`, com áreas em EPSG:5880. Células sem valor não viram zero, e `cobertura_area < 1` indica falta de dado.
- **Previsão de chuva:** ECMWF e GFS acumulam desde o início da rodada, e `chuva_periodo_mm` é a diferença entre horizontes consecutivos (`periodo_h` mostra o tamanho do período).
- **Backtest:** as views escolhem a versão **mais recente** de cada valor. Para simular "o que se sabia no dia", filtre a Silver por `_available_at_utc` e use a rodada da previsão (`rodada_utc`), nunca a chuva observada no lugar da prevista.
- Uma view que dependa de um conjunto ausente é pulada e registrada em `docs/inventory/gold_status.json`.
