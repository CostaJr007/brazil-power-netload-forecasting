"""Modelos do projeto: previsão de ENA por bacia e de carga por subsistema.

validation.py  protocolo de backtest (walk-forward só com o passado, placebo, bootstrap)
timeseries.py  matemática reaproveitada dos repositórios quant (OU, Kalman com inovação)
dados.py       leitura das views Gold e calendário de feriados
ena.py         meteorologia e bacias → ENA
carga.py       calendário e temperatura → carga
"""
