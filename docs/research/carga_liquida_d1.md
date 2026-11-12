# Carga líquida de D+1 contra a programação do ONS (DESSEM)

Pergunta: dá para prever a carga líquida de amanhã (carga − eólica − solar) melhor do que a programação
que o ONS publica na véspera? É a pergunta de "alpha" mais direta que dados públicos permitem.

Script: `scripts/carga_liquida_d1.py`. Resultados: `docs/inventory/carga_liquida_results.json`.
Previsões linha a linha: `data/gold/previsoes_carga_liquida.parquet`.

## Tratamento dos dados (antes do ML)

Feito em `models.dados.tratar_balanco` e `carregar_dessem`; cobre menos de 1% das horas. Ausente, nunca zero.

- **Solar noturna**: solar acima de 50 MW entre 20h e 4h59 locais vira ausente. Ex.: SE em 2022–23.
- **Valores congelados**: eólica ou solar idênticas por 4 h ou mais, acima de 50 MW, viram ausentes. Ex.: solar SE em 2.876 MW a madrugada inteira em 10/11/2024; eólica N.
- **Carga zero**: vira ausente. Ex.: Sul em 04/11/2018.
- **DESSEM publicado pela metade**: 136 subsistema-dias entre jul/2025 e jan/2026. Só entram horas com as duas meias horas.
- **Previsões fora do intervalo físico**: radiação negativa e nuvens fora de 0–100% são limitadas.

## Desenho

- **Alvo**: o balanço horário do ONS (`vw_balanco_carga_liquida`). A solar soma usinas e telhados (MMGD).
- **Referência**: a programação DESSEM (`balanco_dessem_detalhe`) por subsistema e hora:
  - carga = `val_demanda`;
  - eólica = `val_ger_eolica`;
  - solar = `val_ger_fotovoltaica + val_ger_mmgd`.
  - Os dados existem desde 23/05/2025.
- **Informação permitida**: só o que existe na noite de T−1.
  - Geração e carga verificadas até T−2.
  - Previsões GFS e ECMWF emitidas 48 h antes de cada hora (`previous_day2`), com médias ponderadas pela capacidade nas células das usinas.
- **Modelos por peça**:
  - Ridge por hora e GBM sobre a razão `y / nível`, onde o nível é a média de 28 dias da mesma hora até T−2.
  - Combinações com o ONS.
  - Retreino trimestral.
- **Seleção honesta**: para cada peça, a receita é escolhida com dados de 2025 (31/05 a 31/12) e congelada. 2026 (até 07/11) serve só para confirmar.
- **Teste**: intervalo de 95% por bootstrap em blocos de 14 dias sobre a diferença de MAE.

## Duas descobertas antes do ML

1. **O DESSEM tem viés de nível contra o balanço.** Em 2026, o erro médio do ONS (previsto − real) foi:

   | Peça | Subsistema | Viés médio |
   |---|---|---|
   | Carga | SE | +1.153 MW |
   | Carga | NE | +391 MW |
   | Solar | SE | +419 MW |

   Parte disso é diferença de definição entre programação e verificado. Uma mesa corrigiria esse viés
   antes de qualquer ML. Por isso a régua justa é o **ONS corrigido**: a programação menos o erro médio
   dos últimos 28 dias na mesma hora, conhecido até T−2 (`models.renovaveis.corrigir_vies`).
2. **No SIN, os erros do ONS por subsistema se cancelam.**
   - A correlação entre subsistemas fica entre −0,10 e 0,24.
   - A soma dos MAE dos subsistemas é 4.125 MW, mas o MAE do SIN é 2.369 MW.
   - Ganhar em cada subsistema não garante ganhar no SIN.

## Resultado por peça (confirmação 2026, MAE em MW)

| Peça | ONS | ONS corrigido | Receita escolhida em 2025 | MAE da receita | Ganho vs ONS |
|---|---|---|---|---|---|
| Carga | 727 | 560 | média(ML, ONS corrigido) | 512 | 29,6% |
| Eólica | 434 | 434 | média(ML, ONS corrigido) | 397 | 8,5% |
| Solar | 315 | 241 | ONS corrigido | 241 | 23,6% |

- **Carga**: o ML acrescenta cerca de 8% além da correção de viés. A temperatura prevista é o que mais pesa, como no modelo de carga D+1.
- **Eólica**: o DESSEM não tem viés. O ML sozinho perde do ONS (−2,5% a −9,6%), mas a média com o ONS ganha 8,5%, com IC95 que exclui zero.
- **Solar**: o ML (Ridge com radiação e nuvens previstas) só empata com o ONS. Todo o ganho vem de corrigir o viés.

## Resultado na carga líquida

**Receita congelada no SIN:**

| | ONS | ONS corrigido | Receita por peças |
|---|---|---|---|
| 2025 (seleção) | 1.961 | 1.738 (+11,4%) | 1.702 (+13,2%) |
| 2026 (confirmação) | 2.371 | 2.214 (+6,6%) | 2.104 (+11,2%) |

**Testes em 2026 (diferença de MAE, IC95):**

| Comparação | Diferença de MAE | IC95 |
|---|---|---|
| Receita − ONS | −238 MW | [−385, −101] |
| Receita − ONS corrigido | −94 MW | [−171, −19] |

O ganho além da correção de viés, de cerca de 4,2%, é pequeno mas estatisticamente diferente de zero.

**Por subsistema** (2026, ganho vs ONS): SE +28,0%, N +14,1%, NE +9,9%, S +4,4%. Contra o ONS corrigido,
a receita ganha nos quatro, com IC95 que exclui zero em todos.

**Por faixa horária** (SIN 2026, ganho vs ONS):

| Faixa | Ganho |
|---|---|
| Sol, 10–15 h | +15,7% |
| Ponta, 16–21 h | +12,7% |
| Manhã | +9,6% |
| Madrugada | +6,7% |
| Noite | +5,0% |

A rampa diária (máximo − mínimo do dia) também melhora: o erro cai de 3.080 MW (ONS) para 2.695 MW.

**Por mês**:
- O ganho se concentra de março a julho (+14% a +34%).
- Em agosto, setembro e novembro de 2026, a receita perde do ONS (−2% a −6%). É a temporada de ventos fortes no Nordeste, quando o erro da eólica domina.

## O que não funcionou

- **ML puro, sem o ONS como insumo** (`pecas_ridge`): perde do ONS no SIN, −12,7% em 2026. Com previsões de tempo públicas, a programação do ONS carrega informação que não conseguimos reproduzir: agenda de cortes, despacho e previsões próprias de vento.
- **GBM na solar**: era muito pior que o Ridge enquanto a razão `y/nível` não tinha teto. No amanhecer o nível é quase zero e a razão explode. Agora o alvo é limitado a 3, e mesmo assim o GBM não supera o Ridge.
- **Mesmo peso em todos os subsistemas**: o Sul quase não tem ganho (+4,4%).

## Leitura de mercado (honesta)

- **É alpha de previsão, não de preço de D+1.** O PLD de amanhã sai do próprio DESSEM, já publicado na véspera. Prever melhor a carga líquida de D+1 não antecipa esse preço. O valor está em outros lugares:
  - posição intradiária e risco de corte (curtailment) de renováveis;
  - leitura do desvio entre programado e verificado, que entra em encargos;
  - insumo para D+2 em diante, onde ainda não existe programação publicada. É o próximo passo natural.
- **Os dados de seleção são curtos.** São 7 meses de 2025, porque o DESSEM público começa em 23/05/2025. Com mais história, a escolha das receitas pode mudar.
- **Mais de metade do ganho é correção de viés.** É simples, mas é exatamente o tipo de ajuste que uma mesa faz antes de qualquer modelo sofisticado.
- **Previsões de tempo usadas**: Open-Meteo (CC-BY 4.0, uso não comercial). Uso comercial exigiria licença ou dados próprios.
