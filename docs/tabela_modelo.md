# Tabela única de modelagem

`scripts/tabela_modelo.py` junta as fontes em `data/gold/tabela_modelo.parquet` (e `.csv`): **uma linha por subsistema × hora local (UTC−3)**. Um modelo novo só precisa ler esse arquivo.

Cada coluna traz o valor do próprio instante. A última coluna abaixo diz quando o valor fica disponível: para prever o dia T na véspera, use a defasagem indicada.

| Colunas | Origem | Quando se sabe |
|---|---|---|
| `carga` | ONS, carga verificada | Assumido T+2 (defasagem de 2 dias) |
| `programada` | ONS, carga programada | Véspera (T−1); o horário exato de publicação não foi confirmado |
| `temp_prev_48h`, `radiacao_prev`, `vento_prev`, `umidade_prev`, `nuvens_prev` | GFS via Open-Meteo, média das capitais do subsistema | Previsão emitida 48 h antes; pode usar sem defasagem. As quatro últimas só existem desde fev/2024 |
| `temp_analise` | Open-Meteo, análise | Só depois do fato: use apenas para medir o limite de uma previsão perfeita |
| `temp`, `temp_max`, `radiacao`, `vento`, `umidade`, `chuva` | INMET, estações dos 3 estados de maior carga (diário) | Defasagem de 2 dias no backtest; o pacote anual do INMET é publicado com mais atraso |
| `ear`, `ena_pct` | ONS (diário) | Defasagem de 2 dias |
| `eolica`, `solar`, `hidraulica`, `termica` | ONS, balanço por subsistema (média diária) | Defasagem de 2 dias |
| `dia_semana`, `mes`, `feriado`, `vespera`, `pos_feriado`, `ponte` | Calendário | Conhecido com antecedência |

Chuva e ENA **por bacia** continuam em `vw_chuva_x_ena_bacia`, porque o grão é outro (bacia × dia).
