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
| `vw_painel_energia_diario` | dia (SIN) | **Painel de acompanhamento:** balanço, rampa da carga líquida, ENA, EAR, cortes, CMO e PLD estimado |
| `vw_frescor_fontes` | fonte | Última data publicada de cada fonte, dias de atraso e última coleta. Valor negativo significa dado do futuro já publicado (programada e CMO) |
| `vw_balanco_diario` / `vw_balanco_horario_sin` | subsistema e SIN × dia / SIN × hora | Carga, eólica, solar, hidráulica, térmica e carga líquida |
| `vw_renovaveis_diario` | fonte × subsistema × UF × dia | Eólica e solar somadas: geração, capacidade e fator de capacidade |
| `vw_cortes_renovaveis_diario` | fonte × subsistema × dia | Geração cortada por razão (energética, confiabilidade, elétrica) e % do potencial |
| `vw_hidro_subsistema_diaria` | subsistema e SIN × dia | ENA e EAR; percentuais do SIN ponderados |
| `vw_ena_bacia_sem_dupla_contagem` | bacia × dia | ENA por bacia segura para somar |
| `vw_conferencia_soma_bacias` | dia | Soma das bacias contra a ENA do SIN; a diferença deve ser ~0 |
| `vw_ree_diaria` | REE × dia | ENA e EAR por reservatório equivalente |
| `vw_pld_estimado_horario` | subsistema × hora (2021+) | **Estimativa** do PLD: CMO do ONS limitado ao piso e ao teto horário da ANEEL (`origem` indica `cmo`, `piso` ou `teto_horario`) |
| `vw_pld_estimado_diario` | subsistema × dia (2021+) | Média diária da estimativa, limitada ao teto estrutural |

## Regras e cuidados
- **Fuso horário:** só a API de carga (`*_utc`) e a meteorologia têm UTC declarado. As colunas `instante_fonte` e `data_referencia` dos arquivos ONS ficam como publicadas.
- **Média por bacia:** `Σ(valor × área da célula dentro da bacia) / Σ(área com valor)`, com áreas em EPSG:5880. Células sem valor não viram zero, e `cobertura_area < 1` indica falta de dado.
- **Previsão de chuva:** ECMWF e GFS acumulam desde o início da rodada, e `chuva_periodo_mm` é a diferença entre horizontes consecutivos (`periodo_h` mostra o tamanho do período).
- **Backtest:** as views escolhem a versão **mais recente** de cada valor. Para simular "o que se sabia no dia", filtre a Silver por `_available_at_utc` e use a rodada da previsão (`rodada_utc`), nunca a chuva observada no lugar da prevista.
- **Soma das bacias:** não some `vw_ena_bacia_diaria` diretamente. Em 2026 ela traz a linha `AMAZONAS` junto das sub-bacias que a compõem, e o total sai até 34% acima do SIN. Use `vw_ena_bacia_sem_dupla_contagem`.
- **Ritmo das fontes:** cada conjunto é publicado em seu próprio ritmo. `fontes_ausentes` no painel indica o que faltava naquele dia, e `scripts/horarios_publicacao.py` mede os horários reais a partir da Bronze. Lacunas antigas são esperadas: CMO começa em 2020 e os cortes em out/2021.
- **Solar no balanço × usinas:** `solar_mwmed` do balanço é bem maior que a soma de `vw_renovaveis_diario`, porque inclui a geração distribuída (telhados). Usinas + MMGD reproduzem o balanço com correlação de 0,96 a 0,97 em 2024 e 2025, ficando de 500 a 1.500 MWmed acima dele.
- **Cortes:** `corte_mwmed` usa a geração não realizada apurada pelo ONS, com histórico desde out/2021 (eólica) e abr/2024 (solar).
- **PLD estimado:** não é o preço oficial da CCEE, cujo acesso está bloqueado neste ambiente. A CCEE roda o próprio DESSEM, então o valor pode diferir do oficial mesmo fora dos limites. Limites e fontes em `configs/pld_limits.json`.
- Uma view que dependa de um conjunto ausente é pulada e registrada em `docs/inventory/gold_status.json`.
