# Resultados em uma página

O que o projeto entrega, com que régua foi medido e onde estão os detalhes. Todos os números são de
**backtest walk-forward**, com escolha do modelo num período e confirmação num período posterior.
Os intervalos de 95% vêm de bootstrap em blocos de 14 dias. English version: [results.md](results.md).

## A pergunta

O preço de curto prazo (CMO/PLD) sai da programação do ONS (DESSEM), que equilibra a carga líquida
(carga − eólica − solar) com água, térmicas e intercâmbio. Uma mesa de energia ganha vantagem quando
antecipa essa carga líquida melhor do que as referências públicas, ou antes delas.

## Principais números

| Previsão | Régua (o que já existe de graça) | Resultado | Detalhes |
|---|---|---|---|
| **Carga líquida D+1**, SIN horário | Programação DESSEM do ONS | **−11,2% de MAE** em 2026 (2.104 contra 2.371 MW); −94 MW além de uma correção simples do viés do ONS (IC95 de −171 a −19) | [carga_liquida_d1.md](research/carga_liquida_d1.md) |
| **Carga líquida D+2**, SIN horário | Programação de T−1 corrigida por hora e dia da semana | **−25,9% de MAE** em 2026 (2.594 contra 3.501 MW) e antecipa a programação que o ONS ainda vai publicar com erro 25% menor | [carga_liquida_d2.md](research/carga_liquida_d2.md) |
| Carga D+1, por subsistema | Carga programada pela API do ONS | −22% de MAE no SIN na confirmação; −26 MW por hora além da correção de viés | [carga_d1.md](research/carga_d1.md) |
| ENA por bacia (vazão em energia), 1 a 14 dias | Persistência | ganho de 30,5% (1 dia), 19,2% (3), 14,1% (7) e 14,9% (14) com memória e chuva observada | [modelagem_meteorologia_energia.md](research/modelagem_meteorologia_energia.md) |

## O que aprendemos e que vale para qualquer mesa

1. **Corrigir o viés do ONS vem antes de qualquer ML.** A programação DESSEM fica 1,15 GW acima da carga verificada no Sudeste. Só essa correção já ganha 6,6% no SIN em D+1.
2. **A temperatura prevista é o que move a carga.** Reservatórios, ENA e geração passada não acrescentaram nada à carga de D+1.
3. **O valor do tempo previsto cresce com o horizonte.** Em D+1 o ML só ajuda combinado com o ONS. Em D+2 a programação de ontem não conhece a frente de vento de depois de amanhã, e o modelo ganha 33% na eólica.
4. **Os erros por subsistema se cancelam no SIN.** Ganhar em cada região não garante ganhar no total, por isso o SIN é medido à parte.
5. **O preço estimado é censurado.** Em 2022 e 2023, 82% e 98% das horas ficaram no piso do PLD. Um modelo direto de preço precisa tratar isso, e por isso o projeto prevê a carga líquida, que é o que move o preço.
6. **Cortes de renováveis são grandes.** Em 2025–26, 19–20% da eólica e 26% da solar possíveis foram cortados. O nível recente usado como base do modelo já embute isso.

## Do backtest à operação

`scripts/prever_carga_liquida.py` gera a previsão real de amanhã e de depois de amanhã, por subsistema e
hora. Ela usa as receitas congeladas e a previsão do tempo atual nos pontos das usinas.

- **Quando o balanço de ontem ainda não saiu** (por volta das 19h50 de Brasília), o dia é previsto com o horizonte seguinte, que exige menos informação. Exemplo: amanhã sai com a receita de D+2, e o horizonte usado fica registrado na saída.
- **Banda de 80%:** cada previsão sai com faixa de erro tirada dos erros do backtest nos 120 dias anteriores. Em 2026 cobriu 79–80% das horas. Exemplo, SIN em 13/11: média de 59,6 GW, faixa de 56,8 a 64,2 GW.
- **BI:** `scripts/exportar_bi.py` monta as tabelas em modelo estrela e `bi/Energia.pbip` abre o projeto no Power BI ([bi/README.md](../bi/README.md)).
- **Exemplo real:** decisão de 12/11/2026, ainda sem o balanço de 11/11. Para 13/11, a previsão foi de média 59,6 GW e pico de 83,9 GW às 19h. Na semana anterior, o SIN teve média de 55–63 GW e pico de 76–85 GW às 19h.

## Auditoria da semana de 04 a 10/11/2026

`scripts/auditar_previsoes.py` refaz cada previsão como se fossem 22h da véspera da decisão: dados cortados
naquela noite, tempo previsto arquivado e receitas congeladas. Depois compara com o que aconteceu.

| | Modelo (MAE SIN) | Régua | Resultado | Dias vencendo | Hora do pico (±1 h) |
|---|---|---|---|---|---|
| **D+1** | 2.349 MW | ONS 2.139 MW | **perdeu 9,8%** | 4 de 6 | 6 de 6 |
| **D+2** | 3.329 MW | ONS de T−1 corrigido 4.157 MW | **ganhou 19,9%** | 4 de 7 | 7 de 7 |

- **O que deu errado em D+1:** o modelo previu abaixo do real a semana toda, sobretudo na carga do Sudeste (−1,5 GW).
  - **Onda de calor:** de 3 a 7/11, as máximas nas capitais do Sudeste ficaram entre 33 e 37 °C. A carga respondeu ao calor mais do que o histórico ensinou, e o próprio ONS também subestimou.
  - **Previsão do tempo acertou:** o erro médio diário foi de ±0,7 °C.
  - **Viés do ONS virou:** em outubro, a programação do Sudeste ficava de 1 a 2,6 GW acima do real. Em 02 e 04/11 ficou 2,8 e 2,6 GW abaixo. A correção de 28 dias continuou descontando o viés antigo e dobrou o erro. 02/11 foi Finados, ponto fraco já conhecido.
- **Testamos janelas de correção mais curtas:** a de 28 dias continua a melhor em 2025 e em 2026. Nesta semana, nem a de 7 dias venceria o ONS cru. **Não mudamos nada:** ajustar o modelo a uma semana ruim seria superajuste.
- **D+2 se comportou como no backtest:** ganho de 20%, contra 26% esperados.
- **Hora do pico:** acertou em todos os dias nos dois horizontes (18–19h).
- **Lição para a operação:** quando o erro recente do ONS muda de sinal, a receita de D+1 perde força. Um alerta simples ("viés dos últimos 3 dias com sinal oposto ao de 28 dias") avisaria a mesa para dar menos peso à correção.

## Vale a pena uma nova modelagem? Diagnóstico dos resíduos de 2026

`scripts/diagnostico/residuos_2026.py` relaciona o erro fora da amostra da receita atual (304 dias de 2026)
com variáveis candidatas antes de qualquer novo treino.

- **Calor:** existe um padrão no Sudeste. O modelo erra para baixo nos dias mais quentes (−294 MW em D+1, −641 MW em D+2) e para cima nos frios. A relação, porém, é fraca (|correlação| ≤ 0,17).
- **Viés do ONS que virou:** o erro é 23–33% maior nesses dias, mas a direção não é previsível.
- **Segundo estágio walk-forward com essas variáveis:** piorou o MAE no SIN (+4,0% com tempo em D+1, IC95 de +11 a +167 MW). Só uma recalibração por hora e calendário ajudou um pouco em D+2 (−3%, IC95 de −164 a −4 MW).
- **Conclusão:** a temperatura que o modelo já usa (anomalia, graus de resfriamento) captura quase todo o sinal. Calor acumulado e regime do viés servem como **alerta de risco**, não como correção.
- **Intervalo de 80% por reamostragem dos resíduos (Monte Carlo empírico):** bem calibrado em 2026. Cobertura de 80,0% em D+1 (largura de 6,5 GW) e de 80,3% em D+2 (8,2 GW).

### Lógica fuzzy (`scripts/diagnostico/fuzzy_banda.py`)

Risco fuzzy combinado por OU (máximo) de três pertinências: calor acumulado, viés do ONS mudando e dia
especial. Os parâmetros foram escolhidos em ago–dez/2025 e confirmados em 2026.

- **No SIN, o risco não separa os erros:** o MAE é praticamente igual nas faixas baixa, média e alta. O sinal do Sudeste se dilui no total.
- **Banda fuzzy contra banda fixa por hora:** pior em 2026. O Winkler (largura mais penalidade quando o real sai da banda) subiu 120 MW em D+1 (IC95 de +17 a +223) e 432 MW em D+2 (de +226 a +647). A banda alarga quando não precisa e deixa a cobertura nos dias calmos em 70–76%.
- **Peso fuzzy da correção do viés do ONS na carga (D+1):** neutro em 2026 (+0,2%, IC95 de −15 a +16 MW). Ajudou na semana auditada (1.703 contra 1.804 MW), mas uma semana não basta.
- **Conclusão:** fica a banda fixa por hora, calibrada (cobertura de 79–80%). O risco fuzzy fica, no máximo, como texto de alerta.

## Qualidade dos dados (antes de qualquer modelo)

- **Solar noturna e valores congelados no balanço do ONS** viram ausentes. Menos de 1% das horas.
- **Programação DESSEM publicada pela metade** (136 dias-subsistema): entram só horas completas.
- **Último dia do balanço:** sai preliminar e fica fora do backtest.
- **Revisões da carga verificada:** cada uma é preservada na Bronze.
- **Previsões do tempo:** são as **arquivadas como emitidas** (Open-Meteo Previous Runs), não a reanálise. Assim não há "previsão perfeita" escondida.

## Limitações honestas

- **Seleção curta:** o DESSEM público começa em 23/05/2025, então as receitas foram escolhidas com 7 meses.
- **Feriados:** o modelo de carga erra mais (5,3% contra 3,7% do ONS). O ONS conhece a agenda das empresas.
- **PLD oficial:** a CCEE bloqueia o IP de saída (HTTP 403). O preço usado é estimado a partir do CMO, com os limites da ANEEL.
- **Previsão do tempo:** grade de cerca de 110 km. O Open-Meteo é gratuito só para uso **não comercial**; produção comercial exigiria licença ou outra fonte.
- **Primeira publicação:** em operação, o último dia verificado vem na primeira versão (preliminar). O backtest usou valores já revisados.

## Próximo passo natural

Ligar a carga líquida prevista de D+2 ao CMO/PLD estimado (`vw_pld_estimado_horario`) e medir se o erro da
régua em carga líquida antecipa o movimento do preço. É o elo que falta entre "prever melhor" e "decidir melhor".
