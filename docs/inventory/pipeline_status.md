# Estado do pipeline

Verificado: 2026-11-10T21:42:13.814612+00:00; execução: 20261110T214048-714b9af0 (success, há 0 min); status geral: **success**.

Agendador: última execução 2026-11-10T16:40:47.0000000-05:00, código 0; próxima 2026-11-10T16:44:28.0000000-05:00.

| Conjunto | Snapshots de recursos | Linhas válidas | Rejeitadas |
|---|---:|---:|---:|
| ecmwf_ifs_0p25 | 30 | 1737450 | 0 |
| automatic_stations_annual | 1 | 4556568 | 0 |
| merge_daily | 3235 | 785212119 | 21 |
| gfs_0p25 | 22 | 4671810 | 0 |
| balanco-energia-subsistema | 10 | 431879 | 0 |
| balanco_dessem_detalhe | 5 | 960 | 0 |
| balanco_dessem_geral | 5 | 960 | 0 |
| capacidade-geracao | 1 | 5827 | 10 |
| carga-energia-programada | 286 | 399456 | 0 |
| carga-energia-verificada | 456 | 622472 | 0 |
| carga-energia | 9 | 12936 | 0 |
| cmo-semanal | 9 | 1852 | 0 |
| cmo-semi-horario | 7 | 473088 | 0 |
| curva-carga | 9 | 310464 | 0 |
| cvu-usitermica | 1 | 4630 | 0 |
| dados-hidrologicos-res | 44 | 2429005 | 0 |
| dados_hidrologicos_ho | 1 | 39511 | 0 |
| disponibilidade_usina | 1 | 36570 | 0 |
| ear-diario-por-bacia | 9 | 75978 | 0 |
| ear-diario-por-ree-reservatorio-equivalente-de-energia | 9 | 38820 | 0 |
| ear-diario-por-reservatorio | 1 | 23712 | 0 |
| ear-diario-por-subsistema | 9 | 12940 | 0 |
| ena-diario-por-bacia | 9 | 75978 | 0 |
| ena-diario-por-ree-reservatorio-equivalente-de-energia | 9 | 38820 | 0 |
| ena-diario-por-reservatorio | 1 | 48360 | 0 |
| ena-diario-por-subsistema | 9 | 12940 | 0 |
| energia-vertida-turbinavel | 1 | 29180 | 0 |
| fator-capacidade-2 | 63 | 13288279 | 0 |
| geracao-termica-despacho-2 | 1 | 31368 | 0 |
| geracao-usina-2 | 63 | 46372285 | 0 |
| grandezas_fluviometricas | 25 | 315152 | 0 |
| intercambio-nacional | 2 | 65088 | 0 |
| programacao_diaria | 4 | 816384 | 0 |
| programacao_x_previsao | 4 | 116352 | 0 |
| res_cotaareavolume | 1 | 45102 | 0 |
| res_volumeespera | 1 | 10158 | 0 |
| reservatorio | 1 | 162 | 0 |
| restricao_coff_eolica_detail | 1 | 465696 | 0 |
| restricao_coff_eolica_usi | 62 | 13437600 | 0 |
| restricao_coff_fotovoltaica_detail | 1 | 244944 | 0 |
| restricao_coff_fotovoltaica | 32 | 3135888 | 0 |
| usina_conjunto | 1 | 2159 | 0 |
| usina_pqu | 1 | 1318 | 0 |

As contagens não devem ser somadas como se fossem uma única tabela ou medidas de energia. Produtos e períodos podem se sobrepor.

Fontes bloqueadas:

- **ccee_pld**: HTTP 403 do firewall da CCEE para o IP de saída em 10/11/2026 (inclusive www.ccee.org.br). Conector pronto em ccee.enabled=false; habilitar quando a rede tiver acesso. Enquanto isso, CMO semi-horário/semanal do ONS é a referência disponível (PLD horário = CMO do DESSEM limitado aos PLD mínimo/máximo regulados pela ANEEL; não substitui a série oficial).
- **era5_ecmwf_gefs_ana**: Conectores não habilitados nesta versão. ERA5/ECMWF exigem conta e chave CDS locais.
