# Modelagem: meteorologia → bacias → ENA e carga

Primeira rodada de modelos, em 10/11/2026. Código em `models/`, execução com `scripts/modelagem.py`, números completos em `docs/inventory/model_results.json`.

## Por que este alvo

O preço depende de quanta água chega aos reservatórios (ENA) e de quanta carga o sistema atende. Por isso, modelamos essas duas variáveis antes do preço.

Sobre a Axia, o que há de público é pouco: uma plataforma (SPOC) com [previsão de vazões em três horizontes de planejamento](https://www.zedudu.com.br/novo-sistema-com-ia-da-axia-energia-pode-elevar-geracao-de-energia-em-mais-de-12/) e [investimento em IA aplicada a modelos meteorológicos](https://agenciainfra.com/blog/precos-da-energia-devem-seguir-pressionados-ate-janeiro-diz-axia/). Não encontramos fonte sobre como a mesa de comercialização modela. O projeto imita o problema, não um método conhecido da empresa.

## O que veio dos repositórios

| Origem | Matemática | Uso aqui | Resultado |
|---|---|---|---|
| long-short-cointegracao, stat-arb | Ornstein-Uhlenbeck, meia-vida ln2/θ | `models/timeseries.py`: reversão da anomalia da ENA | Útil como baseline e para medir a memória de cada bacia |
| Athena-SDA | Kalman com inovação (NIS) | Regressão com coeficientes variáveis | **Pior que o Ridge fixo** em todos os horizontes |
| Athena-SDA | Walk-forward só com o passado, placebo | `models/validation.py` | **O item mais valioso:** desmontou uma conclusão errada, ver "Carga" |
| vix-engine | GARCH | Não usado | A previsão de ENA e carga é um problema de nível, não de volatilidade |
| crypto-options-gex | Convexidade | Fica para a etapa de preço | Ver `modelos_dos_repositorios.md`, seção 4 |

Os módulos foram reescritos para este problema, sem dependência dos repositórios.

## Protocolo

- **Walk-forward anual:** cada ano de teste só usa modelos treinados com datas anteriores. Média e climatologia também são recalculadas só com o treino.
- **Previsão perfeita é identificada como tal.** O projeto tem só 2 rodadas do ECMWF e 8 do GFS, então não há como avaliar previsão real. Os modelos `*_cenario` usam a chuva ou temperatura observada no período previsto. Eles mostram o **limite superior** do ganho e **não são desempenho alcançável**.
- **Intervalos de confiança:** bootstrap em blocos de 14 dias.

## ENA por bacia (20 bacias, 2021 a 2026)

Skill = fração do erro da persistência eliminada. A previsão é emitida em t, com dados até t, para t+h.

| Modelo | h=1 | h=3 | h=7 | h=14 |
|---|---|---|---|---|
| MAE da persistência (MWmed) | 147 | 374 | 629 | 867 |
| OU (só anomalia atual) | 1,6% | 5,1% | 8,1% | 13,2% |
| Ridge, memória | 29,1% | 16,8% | 12,4% | 14,5% |
| **Ridge, memória + chuva já observada** | **30,5%** | **19,2%** | **14,1%** | **14,9%** |
| Kalman ARX | 5,9% | 1,0% | 1,8% | 3,0% |
| Boosting, memória + chuva observada | 2,2% | −0,8% | −0,3% | 6,1% |
| *Limite: Ridge + chuva futura perfeita* | *34,2%* | *32,6%* | *34,7%* | *36,0%* |

**Leitura:**
- **O modelo linear por bacia é o melhor entre os realizáveis**, com skill positivo em todos os anos e horizontes. Boosting com bacias juntas perde dele: há apenas ~8 anos, e árvores não extrapolam anomalias maiores que as do treino.
- **A chuva já observada ajuda pouco:** de 0,4 a 2,4 pontos sobre a memória. O ganho é significativo em h=1, 3 e 7 e não é em h=14.
- **A previsão de chuva tem o maior potencial:** a chuva futura perfeita leva o skill em h=14 de 14,9% para 36,0%. O ganho real será menor, porque previsão erra, sobretudo em prazos longos.
- **Heterogeneidade:** em h=7, o ganho do Ridge realizável vai de 22,5% (Grande) a −29,5% (Paraguaçu). Doce e Jequitinhonha ficam em torno de zero.
- **Placebo:** o controle mais justo é contra o modelo de memória. O placebo perde 2 anos de treino e acrescenta ruído, então a diferença contra ele superestima o valor da chuva.

## Carga diária por subsistema (2022 a out/2026)

Previsão do dia T emitida na manhã de T−1, com a verificada conhecida até T−2 (premissa conservadora). O concorrente é a carga programada do ONS, com erro médio (MAPE) de 2,72%.

| Modelo | MAPE | Redução de MAE sobre o ONS |
|---|---|---|
| Mesmo dia da semana anterior | 4,15% | −72,6% |
| **ONS + erro médio dos últimos 28 dias** | **2,20%** | **20,7%** |
| ONS corrigido por boosting | 2,25% | 17,4% |
| Boosting com calendário e temperatura passada | 2,42% | 2,2% |
| *Limite: ONS corrigido + temperatura perfeita* | *1,96%* | *29,0%* |
| *Limite: boosting + temperatura perfeita* | *1,78%* | *32,8%* |

**Leitura:**
- **A regra simples ganhou do machine learning.** Corrigir o viés recente da programada foi melhor que o boosting que corrige o ONS (diferença de 18 MWmed, IC 95% de 3 a 34).
- **A vantagem está concentrada em 2022 e 2023:** a regra reduziu o erro em 42,7% e 28,5% nesses anos, e em apenas 0,4% em 2024. O viés do ONS diminuiu, então o ganho futuro não deve ser extrapolado da média.
- **Sem o ONS, o modelo não basta no SE/CO:** o boosting com calendário e temperatura passada é 12% pior que o ONS, o maior subsistema.
- **A temperatura do dia alvo é o que falta.** Ela reduz o MAPE do boosting de 2,42% para 1,78%, mas só com previsão perfeita.

## Limitações

- **Carga programada:** a API devolve uma versão de cada intervalo. Assumimos que é o programa da véspera. Se for revisado depois, o ONS parece melhor do que era, e a vantagem real dos modelos seria maior.
- **Temperatura:** média das estações INMET dos 3 estados de maior carga de cada subsistema, sem ponderar por população.
- **Dados:** a ENA é a verificada atual; revisões posteriores do ONS não são reconstruídas. 6 bacias só têm dados desde 2026 e ficaram de fora, entre elas Madeira e Xingu.
- **Meia-vida OU em bacias longas** (São Francisco: 268 dias): reflete secas e cheias plurianuais, não um retorno rápido à média. Não usar como prazo de operação.

## Próximos passos, por valor

1. **Histórico de previsões reais de chuva e temperatura.** É o que transforma os limites acima em resultado. O coletor diário já acumula rodadas; para treinar antes, avaliar reprevisões históricas (GEFS, ECMWF).
2. **Agregar a ENA por subsistema** e usar a topologia em cascata das bacias, o que deve ajudar Paraná e São Francisco.
3. **Modelo de preço:** CMO condicionado a ENA prevista, EAR e carga líquida, com os limites do PLD aplicados depois.

Fontes da pesquisa: [estudo do IFMG com LSTM para ENA e EAR](https://repositorio.ifmg.edu.br/items/17e8e09e-b8bf-400c-9d0e-fe27024677c8), [tese da Unifei sobre preço e variáveis hidrológicas](https://repositorio.unifei.edu.br/jspui/bitstream/123456789/4124/1/Tese_2024041.pdf).
