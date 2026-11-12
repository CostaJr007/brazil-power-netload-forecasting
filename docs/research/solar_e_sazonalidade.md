# Usinas solares, incidência e sazonalidade da carga

Análise de 10/11/2026. Números em `docs/inventory/solar_usinas.json`, `solar_irradiancia.json` e `sazonalidade_carga.json`. Código em `scripts/solar_usinas.py`, `scripts/solar_irradiancia.py` e `models/sazonalidade.py`.

## Onde estão as usinas

O conjunto `fator-capacidade-2` do ONS lista as solares com coordenadas: 99 conjuntos, cerca de 25,5 GW. O total pode estar levemente superestimado, porque há nomes duplicados (Rio Brilhante aparece duas vezes). Geração distribuída de telhado não entra.

| Estado | Capacidade (MW) |
|---|---|
| MG | 9.626 |
| BA | 3.445 |
| PI | 2.775 |
| CE | 2.516 |
| RN | 2.088 |

O ranking completo, com latitude e longitude, está em `solar_usinas.json`.

## Melhor fonte de incidência: a medição da própria usina

`restricao_coff_fotovoltaica_detail` (abril/2024 em diante) traz irradiância medida, geração e o indicador de hora com corte.

| Teste | Resultado |
|---|---|
| Radiação de satélite/reanálise (NASA POWER) × geração | Correlação de 0,35 a 0,6; quase não supera a climatologia |
| Irradiância medida × geração, todas as horas | 0,38 a 0,82 |
| Irradiância medida × geração, **só horas sem corte** | **0,84 a 0,97 em 11 das 12 usinas** |
| Geração estimada pela irradiância, de jan/2026 em diante | Reduz de 36% a 87% o erro da climatologia em 8 de 9 usinas |

**Leitura:** o sol explica a geração quando a usina pode gerar. A correlação fraca vinha principalmente dos cortes e da curva achatada de usinas com rastreador. Assu Sol é exceção (0,57, sem ganho) e merece checagem de sensor. A medição só existe depois do fato: para prever, ainda é preciso previsão de irradiância.

**Cortes:** o percentual de horas diurnas com restrição registrada subiu de 5% a 21% em meados de 2024 para 60% a 80% em boa parte de 2025 e 2026. Duas ressalvas: uma hora conta se ao menos uma usina do conjunto teve restrição, então é limite superior; e o grupo de usinas muda, pois várias só entram depois. Concentra-se entre 8h e 13h. O campo `corte_pct_da_referencia_quando_informada` não mede a perda anual, porque a geração de referência vem preenchida em só parte das horas.

## Sazonalidade do sol (média das usinas com histórico, NASA POWER)

| Mês | kWh/m²/dia | Claridade (real ÷ céu limpo) | Fator de capacidade |
|---|---|---|---|
| Janeiro | 5,93 | 0,75 | 23,2% |
| Abril | 5,51 | 0,84 | 21,9% |
| Junho | 4,79 | 0,88 | 19,1% |
| Setembro | 6,57 | 0,93 | 22,0% |
| Novembro | 6,32 | 0,81 | 24,1% |

Junho tem o menor sol. Setembro tem o maior sol e o céu mais limpo. No verão o potencial é alto, mas as nuvens reduzem o aproveitamento.

## Modelo de carga fatiado (confirmação em 2025 e 2026)

Treinar um modelo por estação ou por janela de meses **não superou o modelo único** em geral: MAPE de 2,69% e 2,65% contra 2,67%, com intervalos de confiança incluindo zero. O modelo único foi o escolhido em 2023 e 2024.

| Fatia | ONS | Modelo único |
|---|---|---|
| Inverno | 2,61% | 2,31% |
| Outono | 3,06% | 2,56% |
| Primavera | 3,10% | 2,53% |
| Verão | 3,54% | 3,41% |
| Dezembro | 4,31% | 4,41% |
| Madrugada (0h a 5h) | 2,26% | 2,32% |
| Sol (10h a 15h) | 4,28% | 3,45% |
| Ponta (16h a 21h) | 2,76% | 2,30% |
| Feriados | 3,66% | **5,26%** |
| Sul no verão | 4,66% | **5,52%** |

**Pontos fracos:** feriados e verão no Sul, onde o ONS é melhor. No inverno do Sul o modelo por janela de meses caiu de 3,81% para 3,14%, mas é uma observação feita depois de olhar os dados: precisa ser testada antes de ser adotada.

## Sazonalidade da carga (índice mensal, 2022 a 2025)

| Subsistema | Mês de pico | Mês de vale |
|---|---|---|
| SE/CO | Março (1,08) | Julho (0,92) |
| Sul | Fevereiro (1,14) | Maio (0,93) |
| Nordeste | Novembro (1,06) | Julho (0,93) |
| Norte | Outubro (1,09) | Janeiro (0,92) |
