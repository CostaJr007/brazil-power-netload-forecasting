"""Project models: inflow (ENA) by basin, load by subsystem and net load (load − wind − solar).

validation.py   backtest protocol (past-only walk-forward, placebo, block bootstrap)
timeseries.py   maths reused from earlier quant projects (Ornstein-Uhlenbeck, Kalman with innovation)
dados.py        Gold readers, data cleaning and holiday calendar
ena.py          weather and basins → inflow
carga.py        calendar and temperature → daily load
carga_d1.py     hourly D+1 load with forecast temperature
renovaveis.py   wind, solar and load components → net load, D+1 and D+2
operacional.py  daily operational forecast, horizon fallback and 80% prediction band
"""
