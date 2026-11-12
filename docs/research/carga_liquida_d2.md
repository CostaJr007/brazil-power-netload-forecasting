# Carga líquida de D+2: antes de o ONS publicar a programação

Continuação de [carga_liquida_d1.md](carga_liquida_d1.md). Em D+1 a programação do ONS (DESSEM) já está
publicada, e o preço de amanhã sai dela. Em **D+2** ainda não existe programação: quem prevê bem aqui
antecipa a informação que vai formar o preço daquele dia.

Comando: `scripts/carga_liquida_d1.py --horizonte 2`. Resultados: `docs/inventory/carga_liquida_dmais2_results.json`.
Previsões linha a linha: `data/gold/previsoes_carga_liquida_dmais2.parquet`.

## O que se sabe na hora da decisão (22h do dia D, alvo T = D+2)

| Informação | Disponível até | Em D+1 era |
|---|---|---|
| Carga, eólica e solar verificadas | T−3 (D−1) | T−2 |
| Programação do ONS | só a de T−1 (amanhã) | a do próprio T |
| Previsão do tempo | rodada emitida 72 h antes de cada hora (`previous_day3`) | 48 h |

As previsões de 72 h e de 96 h (para um futuro D+3) foram baixadas com `--dias 3 4` nos dois scripts de download.

Os testes garantem que alterar os dados de T−2, T−1 ou T não muda nenhuma variável usada para prever T:
- `test_d_mais_2_nao_usa_geracao_de_t_menos_2`
- `test_carga_d_mais_2_nao_usa_carga_de_t_menos_2`
- `test_ons_ant_em_d_mais_2_e_a_programacao_de_t_menos_1`
- `test_vies_por_dia_da_semana_...`

## A régua: o que uma mesa faria sem modelo

A ideia é usar a programação de amanhã (`ons_ant`) como previsão de depois de amanhã. Testei três versões:

| Régua (SIN 2026) | MAE (MW) |
|---|---|
| `ons_ant`: programação de T−1 sem ajuste | 4.722 |
| `ons_ant_corrigido`: com o viés médio da mesma hora | 4.655 |
| **`ons_ant_semana`**: com o viés da mesma hora **e dia da semana** (últimas 4 ocorrências) | **3.501** |

- **A versão crua é fraca demais.** Na segunda-feira ela usa a programação de domingo. Um primeiro teste contra `ons_ant_corrigido` deu ganho de 42%, alto demais para ser justo.
- **A régua oficial é `ons_ant_semana`.** Ela corrige justamente a troca de dia da semana (`models.renovaveis.corrigir_vies_semana`).

## Resultado (receita escolhida em 2025, confirmada em 2026)

**Peças (2026, MAE em MW):**

| Peça | Régua `ons_ant_semana` | Receita escolhida em 2025 | MAE | Ganho |
|---|---|---|---|---|
| Carga | 847 | média Ridge + GBM | 602 | 29,0% |
| Eólica | 696 | GBM | 469 | 32,6% |
| Solar | 373 | média(ML, régua) | 302 | 19,0% |

**Carga líquida no SIN:**

| | Régua | Receita | Ganho | ONS do próprio dia (só sai depois), corrigido |
|---|---|---|---|---|
| 2025 (seleção) | 2.937 | 2.246 | 23,5% | 1.763 |
| 2026 (confirmação) | 3.501 | 2.594 | **25,9%** | 2.211 |

- **Teste em 2026:** receita − régua = −892 MW, IC95 [−1.195, −580].
- **Ganho em todos os subsistemas,** com IC95 que exclui zero: N +26,8%, NE +27,8%, S +28,4%, SE +27,9%.
- **Por faixa horária:**

  | Faixa | Ganho |
  |---|---|
  | Noite | +37% |
  | Ponta | +34% |
  | Madrugada | +27% |
  | Manhã | +23% |
  | Sol | +15% |

- **Por mês:** ganho em 10 de 11 meses. A exceção é agosto (−2,6%).

**Custo de decidir um dia mais cedo:**
- A receita de D+2 erra 461 MW a mais (IC95 [299, 636]) que o ONS corrigido do próprio dia, que o ONS publica um dia depois.
- Mesmo assim, fica perto da programação crua do ONS (2.366 MW).

## Antecipar a programação do ONS

Este é o uso de mercado. O alvo deixa de ser o verificado e passa a ser a programação que o ONS vai publicar
amanhã para T, que é o insumo do preço de T.

| Previsão da programação de T (SIN 2026) | MAE (MW) |
|---|---|
| Programação de T−1, crua | 3.983 |
| Régua `ons_ant_semana` | 3.021 |
| **Receita por peças** | **2.256** |

A receita antecipa a programação do ONS com erro 25% menor que a melhor régua simples.

## Leitura honesta

- **O ganho vem quase todo da previsão do tempo de 72 h.** A régua não conhece o tempo de depois de amanhã, o ML conhece. Sem previsão (`ridge_sem_previsao`), o ML perde para a régua na eólica e na solar.
- **A eólica mostra isso bem.** Em D+1, o ML só ajudava combinado com o ONS. Em D+2, a programação de ontem não sabe nada da frente de vento de depois de amanhã, e o GBM ganha 33% sozinho.
- **Na solar, o ONS de T−1 ainda carrega informação útil:** a receita é a média do ML com a régua.
- **Os limites são os mesmos do D+1:**
  - a amostra de seleção é curta (o DESSEM público começa em 23/05/2025);
  - a previsão do tempo é de grade grossa;
  - o Open-Meteo é só para uso não comercial.
- **Isso ainda não é preço.** O próximo passo é ligar a carga líquida prevista de D+2 ao CMO/PLD estimado (`vw_pld_estimado_horario`) e medir se o erro na carga líquida antecipa o movimento do preço.
