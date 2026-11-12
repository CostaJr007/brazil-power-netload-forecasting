# Estado do pipeline

Verificado: 2026-11-12T17:08:13.984573+00:00; execução: 20261112T155931-3f8f5504 (partial, há 66 min); status geral: **attention**.

Agendador: última execução 2026-11-12T10:59:29.0000000-05:00, código 1; próxima 2026-11-12T12:14:28.0000000-05:00.

**Alertas:**

- Último relatório tem 66 min: o agendamento pode ter parado ou execuções estão caindo.
- Agendador: última execução terminou com código 1 (0 = sucesso).

| Conjunto | Snapshots de recursos | Linhas válidas | Rejeitadas |
|---|---:|---:|---:|
| ecmwf_ifs_0p25 | 60 | 3474900 | 0 |
| automatic_stations_annual | 9 | 45026904 | 0 |
| merge_daily | 3236 | 785454843 | 21 |
| gfs_0p25 | 43 | 9131265 | 0 |
| balanco-energia-subsistema | 10 | 432119 | 0 |
| balanco_dessem_detalhe | 531 | 99725 | 0 |
| balanco_dessem_geral | 6 | 1152 | 0 |
| capacidade-geracao | 1 | 5827 | 10 |
| carga-energia-programada | 294 | 399840 | 0 |
| carga-energia-verificada | 464 | 622856 | 0 |
| carga-energia | 9 | 12944 | 0 |
| cmo-semanal | 9 | 1852 | 0 |
| cmo-semi-horario | 7 | 473472 | 0 |
| curva-carga | 9 | 310656 | 0 |
| cvu-usitermica | 1 | 4630 | 0 |
| dados-hidrologicos-res | 44 | 2429353 | 0 |
| dados_hidrologicos_ho | 1 | 46762 | 0 |
| disponibilidade_usina | 1 | 44202 | 0 |
| ear-diario-por-bacia | 9 | 76046 | 0 |
| ear-diario-por-ree-reservatorio-equivalente-de-energia | 9 | 38844 | 0 |
| ear-diario-por-reservatorio | 1 | 23864 | 0 |
| ear-diario-por-subsistema | 9 | 12948 | 0 |
| ena-diario-por-bacia | 9 | 76046 | 0 |
| ena-diario-por-ree-reservatorio-equivalente-de-energia | 9 | 38844 | 0 |
| ena-diario-por-reservatorio | 1 | 48670 | 0 |
| ena-diario-por-subsistema | 9 | 12948 | 0 |
| energia-vertida-turbinavel | 1 | 36476 | 0 |
| fator-capacidade-2 | 63 | 13299607 | 0 |
| geracao-termica-despacho-2 | 1 | 38424 | 0 |
| geracao-usina-2 | 63 | 46405453 | 0 |
| grandezas_fluviometricas | 25 | 315506 | 0 |
| intercambio-nacional | 2 | 65280 | 0 |
| programacao_diaria | 6 | 1224960 | 0 |
| programacao_x_previsao | 6 | 174528 | 0 |
| res_cotaareavolume | 1 | 45102 | 0 |
| res_volumeespera | 1 | 10158 | 0 |
| reservatorio | 1 | 162 | 0 |
| restricao_coff_eolica_detail | 1 | 569184 | 0 |
| restricao_coff_eolica_usi | 62 | 13452192 | 0 |
| restricao_coff_fotovoltaica_detail | 32 | 21019248 | 0 |
| restricao_coff_fotovoltaica | 32 | 3143952 | 0 |
| usina_conjunto | 1 | 2159 | 0 |
| usina_pqu | 1 | 1318 | 0 |

As contagens não devem ser somadas como se fossem uma única tabela ou medidas de energia. Produtos e períodos podem se sobrepor.

Fontes bloqueadas:

- **ccee_pld**: HTTP 403 do firewall da CCEE para o IP de saída em 10/11/2026 (inclusive www.ccee.org.br). Conector pronto em ccee.enabled=false; habilitar quando a rede tiver acesso. Enquanto isso, CMO semi-horário/semanal do ONS é a referência disponível (PLD horário = CMO do DESSEM limitado aos PLD mínimo/máximo regulados pela ANEEL; não substitui a série oficial).
- **era5_ecmwf_gefs_ana**: Conectores não habilitados nesta versão. ERA5/ECMWF exigem conta e chave CDS locais.
