# Modelos dos repositórios anteriores aplicados ao setor elétrico

Análise de 10/11/2026 dos repositórios de CostaJr007 (long-short-cointegracao, b3-statistical-arbitrage-pairs-trading, b3-index-cash-and-carry, b3-vix-volatility-engine, crypto-options-gex, Athena-SDA). Para cada família de modelos: o que ela faz, como se traduz para energia e **um teste rápido com os dados reais deste projeto** (views em `data/gold/energia.duckdb`). Os testes são exploratórios e ainda não são modelos validados.

## Diferença essencial entre os mercados

No Brasil não existe bolsa líquida de energia com futuros e opções como a B3 tem para índice, dólar e juros. A comercialização acontece em contratos bilaterais e em balcão (ex.: BBCE), com preço de referência no PLD, que deriva do CMO calculado pelos modelos do ONS e da CCEE. Consequências:
- **Funcionam diretamente:** modelos de séries temporais (cointegração, OU, Kalman, mudança de regime, anomalia) aplicados a carga, ENA, EAR, CMO e spreads entre submercados.
- **Funcionam como analogia:** GEX, VIX e cash-and-carry. Não há opções nem futuros de energia nos dados, mas os conceitos (convexidade, volatilidade implícita, custo de carregamento) têm equivalentes físicos.

## 1. Cointegração + Dickey-Fuller + Ornstein-Uhlenbeck (long-short, stat-arb)

**Nos repositórios:** Engle-Granger com e sem tendência, ADF nos resíduos, meia-vida OU `ln2/θ`, z-score com entrada, saída e stop, regra dos 3 prazos e correção Benjamini-Hochberg (FDR).

**Em energia:** spreads de preço entre submercados (SE×S, SE×NE, SE×N) e o erro da previsão de carga do ONS.

| Teste (dados reais) | Resultado |
|---|---|
| CMO semanal SE×S, 2018+ (463 semanas) | Engle-Granger p≈0; meia-vida do spread 2,0 semanas; **spread ≈ 0 em 91% das semanas** |
| CMO semanal SE×NE | p≈0; meia-vida 2,3 semanas; spread ≈ 0 em 67% das semanas; média +31 R$/MWh |
| CMO semanal SE×N | p=0,16 (sem cointegração a 5%); spread ≈ 0 em 63% das semanas |

**Leitura:** a "cointegração" SE×S é quase mecânica. Os preços são iguais enquanto não há congestionamento na transmissão, e o spread só aparece quando o intercâmbio bate no limite. A abordagem certa **não** é z-score clássico. É modelar *quando* o spread abre: uma variável de congestionamento (intercâmbio ÷ limite, que já está em `intercambio-nacional`) combinada com OU só nos períodos descolados. A regra dos 3 prazos e o FDR do long-short são úteis para não se enganar testando muitos pares.

**Cuidado:** séries de energia têm **sazonalidade forte**. ADF e cointegração em séries com ciclo anual dão falsa reversão à média. Teste sobre anomalias (ex.: ENA em % da MLT, carga menos o perfil sazonal), nunca sobre o nível bruto.

## 2. OU no erro da previsão de carga: o "DART" brasileiro

| Subsistema (diário, 2021+) | Viés médio (verificada − programada) | Meia-vida | Autocorrelação lag 1 / lag 7 |
|---|---|---|---|
| SE/CO | +1,41% | 1,2 dia | 0,56 / 0,18 |
| S | +2,09% | 1,2 dia | 0,57 / 0,30 |
| NE | +1,62% | 1,5 dia | 0,64 / 0,22 |
| N | +1,25% | 1,0 dia | 0,48 / 0,05 |

**Leitura:** é o resultado mais promissor. A carga programada do ONS **subestima sistematicamente** a realizada (viés positivo em todos os subsistemas), e o erro de hoje é **parcialmente previsível pelo de ontem** (autocorrelação de 0,5–0,64). Um modelo AR/OU sobre esse erro, mais temperatura prevista (ECMWF `2t`) e calendário, é uma estratégia bem definida: prever onde o operador vai errar.

## 3. Volatilidade: GARCH (vix-engine)

| Teste | Resultado |
|---|---|
| CMO semi-horário SE, média diária (2.464 dias) | Autocorrelação de \|ΔCMO\|: lag 1 = 0,15; lag 5 = 0,05 |

**Leitura:** há pouco agrupamento de volatilidade no estilo GARCH. O CMO também chega a **zero** (com reservatório cheio), o que impede retornos logarítmicos. A volatilidade do preço de energia é dominada pelo **regime do reservatório** (seção 4), não por choques que se propagam como na bolsa. Use GARCH como baseline de risco. Para o preço, modelos de **mudança de regime** (Markov switching) ou regressão condicionada à EAR tendem a funcionar melhor.

## 4. Convexidade preço × reservatório: o análogo do GEX (crypto-options-gex)

No GEX, *long gamma* amortece movimentos e *short gamma* os amplifica. Em energia, o equivalente é a **curvatura do preço em função da EAR**:

| EAR SE | Semanas | CMO SE mediano | CMO SE p90 |
|---|---|---|---|
| 10–20% | 27 | 227 | 725 |
| 20–30% | 72 | 285 | **1.020** |
| 30–40% | 50 | 195 | 548 |
| 40–50% | 93 | 165 | 350 |
| 50–60% | 64 | 51 | 320 |
| 60–70% | 106 | 70 | 320 |
| 70–80% | 27 | **0** | 19 |
| 80–87% | 24 | **0** | 0 |

**Leitura:** com a EAR acima de ~70% o preço fica no piso, um regime "long gamma" em que choques de chuva quase não movem o preço. Abaixo de ~40% a cauda explode (p90 de 500 a 1.000 R$/MWh), um regime "short gamma" em que a mesma chuva a menos move muito o preço. É o "zona de alta convexidade" citado na pesquisa inicial.

**Modelo:** regressão monotônica ou por quantis do CMO contra EAR, ENA prevista e carga líquida. Um "zero-gamma level" equivalente seria a faixa de EAR onde a sensibilidade do preço muda de patamar.

## 5. Volatilidade implícita: o análogo do VIXBOVA

Não há opções de energia, mas existe uma medida **forward-looking** de incerteza: o **espalhamento entre os membros** de uma previsão de chuva por ensemble (GEFS, 31 membros; ECMWF ENS, 51). Quanto maior o desvio entre os cenários de chuva na bacia, maior a incerteza da ENA futura. Funciona como um "VIX hidrológico" por bacia. Requer coletar o GEFS ou o ECMWF ENS, já listados como próxima fonte em `meteorologia_bacias_e_modelos.md`.

## 6. Cash-and-carry e curva DI

- **Custo de carregamento:** energia elétrica não se armazena, mas a **água no reservatório sim**. O "valor da água" do ONS (custo de oportunidade de usar a água hoje em vez de guardá-la) faz o papel do *convenience yield*.
- **Curva DI:** útil para trazer a valor presente contratos de energia de longo prazo (PPAs) e comparar preços a termo. É baixa prioridade enquanto não houver preços a termo (BBCE) nos dados.

## 7. Athena-SDA: o mais reaproveitável para a fase de modelagem

| Componente do Athena | Aplicação em energia |
|---|---|
| **Filtro de Kalman com inovação** (`innovation.py`, Zollo & Weigel) | Estado-espaço para ENA e carga (nível + tendência). A inovação normalizada detecta anomalias e revisões de dados |
| **Detecção de mudança de regime** (`changepoint.py`, PELT) | Achar quebras estruturais de forma objetiva (PLD horário em 2021, crise hídrica, MMGD) e escolher a janela de treino de cada modelo |
| **Isolation Forest "past-only"** | Anomalias de qualidade nos dados da Silver e estados incomuns do sistema |
| **Walk-forward past-only + placebo + Mann-Whitney + pré-registro** | O protocolo de backtest do projeto: treinar só com o passado, testar em períodos placebo e fixar hipóteses antes de olhar o resultado |
| **DFA / persistência** | Memória longa da hidrologia. O fenômeno de Hurst nasceu justamente em hidrologia, no rio Nilo |
| **DCCA** (correlação cruzada sem tendência) | Relação chuva → ENA em várias escalas de tempo |
| **Dempster-Shafer e Kelly** | Combinar sinais fracos (ECMWF × GFS × MERGE) e dimensionar posição |
| **Clima espacial como contexto** | O equivalente aqui é o ENSO (índice ONI da NOAA): uma fonte nova, gratuita e mensal, a adicionar |

Teste de persistência (anomalia da ENA em % da MLT, AR(1) diário desde 2018):

| Bacia | Meia-vida da anomalia |
|---|---|
| Grande | 47 dias |
| Iguaçu | 37 dias |
| Paranaíba | 30 dias |
| Tocantins | 25 dias |
| Jacuí | **6 dias** |

As bacias grandes do SE/CO têm "memória" de 1 a 1,5 mês: uma anomalia de ENA hoje diz muito sobre as próximas semanas. As do Sul esquecem em dias, coerente com a correlação chuva × ENA mais baixa lá.

## Roteiro sugerido para a fase de modelagem

1. **Infraestrutura de validação** (Athena): walk-forward past-only, baselines ingênuos (persistência, climatologia), métricas e placebo. **Vem antes de qualquer modelo.**
2. **Erro da previsão de carga** (OU/AR + temperatura ECMWF + calendário): é o sinal mais claro encontrado.
3. **ENA por bacia:** AR(1) sobre a anomalia como baseline, depois Kalman com chuva observada e prevista como entrada (ARX/estado-espaço), depois LSTM tipo hindcast/forecast.
4. **Preço condicionado ao regime:** convexidade CMO × EAR (quantis/monotônica) e Markov switching. GARCH só como baseline de risco.
5. **Spreads entre submercados:** congestionamento + OU nos períodos descolados.
6. **Mudança de regime** para definir as janelas de treino; **ensemble spread** como "VIX hidrológico" quando GEFS ou ECMWF ENS estiverem no pipeline.

## Reaproveitamento de código

Os módulos dos repositórios são pequenos e testados (OU, Engle-Granger, ADF, Fisher, GARCH, Kalman, change-point). Em vez de depender dos outros repositórios, é mais limpo **copiar e adaptar** os modelos para um pacote `models/` deste projeto, com testes próprios. Duas adaptações são obrigatórias:
- **Valores críticos:** usar MacKinnon via `statsmodels` em vez dos críticos fixos da planilha, porque as amostras aqui têm tamanhos muito variados.
- **Sazonalidade:** aplicar os modelos sobre anomalias dessazonalizadas, nunca sobre o nível bruto.
