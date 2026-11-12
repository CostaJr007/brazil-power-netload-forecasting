# Previsão horária da carga do dia seguinte (D+1)

Rodada de 10/11/2026. Teste walk-forward anual de 2023 a 08/11/2026 nos 4 subsistemas. Números completos em `docs/inventory/carga_d1_results.json` e `carga_fontes_results.json`. Código em `models/carga_d1.py` e `models/carga_fontes.py`.

Informação usada para prever o dia T: carga verificada até T−2 e temperatura prevista 48 h antes de cada hora (GFS arquivado, Open-Meteo). Com isso, a previsão pode ser feita antes de o ONS publicar a programada.

## Quanto cada fonte ajuda (erro horário médio, MAPE)

| Variáveis somadas ao histórico de carga e calendário | Prever a carga verificada | Prever a programada do ONS |
|---|---|---|
| Só histórico e calendário | 3,05% | 2,10% |
| + temperatura prevista | **2,63%** | **1,99%** |
| + clima observado (sol, vento, umidade, chuva) | 2,83% | 2,01% |
| + reservatórios (EAR, ENA) | 3,03% (sem efeito significativo) | 2,11% (sem efeito) |
| + geração das usinas | 3,05% (sem efeito) | 2,10% (sem efeito) |
| Tudo junto, Ridge | **2,58%** | **1,97%** |
| Tudo junto, boosting | 2,75% | 2,16% |

Referência: a programada do ONS erra 3,09% contra a verificada, no mesmo período.

**Leitura:**
- **Temperatura prevista é a variável decisiva.** No SE/CO, o erro cai de 3,16% para 2,22%.
- **Reservatórios e geração não explicam a carga.** Faz sentido físico: consumo depende de clima e calendário, não de quanta água há na represa. Esses dados voltam na etapa de preço, onde têm efeito.
- **Modelo mais adequado: um Ridge por hora do dia.** Ganhou do boosting nos dois alvos.
- **Combinação com o ONS:** a média de ONS corrigido, Ridge e boosting foi a melhor em 2023 e 2024, e confirmou em 2025 e 2026 (MAE 12,5% menor que o ONS e 4,6% menor que a regra de viés, IC 95% excluindo zero).

## Limites
- Vento, radiação e umidade **previstos** não foram testados: o Open-Meteo retornou erro 503 de forma persistente. O erro do ONS sobe de ~2,2% de madrugada para ~4,6% ao meio-dia, e a geração solar distribuída é hipótese ainda sem teste.
- O clima observado do INMET vem de pacotes anuais publicados com atraso. Em produção, precisaria de uma fonte diária.
- A temperatura é a média simples de 3 ou 4 capitais por subsistema, não ponderada pela carga.
- "Tudo junto" foi avaliado em todo o período, sem separar um trecho de confirmação.
- A programada é assumida como a publicada na véspera; o horário exato não foi confirmado.
- **Revisões:** a verificada do ONS é reescrita depois da primeira publicação (`din_atualizacao` chega a mais de um ano após o dia). O backtest usa o valor final, não o que estava publicado na época, então o erro real pode ser um pouco maior. A defasagem de 2 dias é coerente com o observado em 10/11/2026 à noite, quando a verificada mais recente era a de 09/11.

## Próximo passo: preço
Prever CMO ou PLD estimado em dois estágios: primeiro o regime (piso, normal ou teto), depois o nível por quantis, com EAR, ENA, carga líquida prevista e erro da carga de D+1 como entradas.

Fontes: [modelos lineares por hora em previsão D+1](https://ir.cwi.nl/pub/28449/28449.pdf) · [comparação Ridge, Lasso e rede neural no GEFCom2014](https://10wvvw.easychair.org/publications/preprint/Jcdq/open) · [Open-Meteo, Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api)
