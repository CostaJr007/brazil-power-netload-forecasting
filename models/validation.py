"""Backtest protocol, adapted from a past-only walk-forward design.

Three rules keep results from looking better than they are:
1. Walk-forward: each test year is forecast by a model that only saw earlier dates.
2. Baselines: a model only matters if it beats persistence and climatology.
3. Placebo: if replacing an explanatory variable by one from another year does not hurt the model, the "improvement"
   attributed to it was not real.
"""
import numpy as np
import pandas as pd


def annual_folds(first_year, last_date):
    """Devolve (início, fim_exclusivo) de cada ano de teste, cortando o último em last_date."""
    last = pd.Timestamp(last_date)
    folds = []
    for year in range(first_year, last.year + 1):
        start, end = pd.Timestamp(year, 1, 1), pd.Timestamp(year + 1, 1, 1)
        folds.append((start, min(end, last + pd.Timedelta(days=1))))
    return folds


def placebo_shift(series, days=730):
    """Desloca a série 2 anos: mantém a sazonalidade e destrói a informação do tempo real daquele dia."""
    return series.shift(days)


def mae(y, pred):
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(pred))))


def skill(mae_model, mae_baseline):
    """Fração do erro do baseline eliminada: 0 empata, 1 é perfeito, negativo é pior que o baseline."""
    return 1.0 - mae_model / mae_baseline


def block_bootstrap_diff(dates, abs_err_a, abs_err_b, block_days=14, n=2000, seed=0):
    """IC 95% de MAE(a) − MAE(b). Blocos preservam a autocorrelação dos erros, que uma reamostragem simples ignoraria."""
    frame = pd.DataFrame({"d": pd.to_datetime(dates), "x": np.asarray(abs_err_a) - np.asarray(abs_err_b)})
    daily = frame.groupby("d")["x"].mean()
    blocks = daily.groupby((daily.index - daily.index[0]).days // block_days).mean().to_numpy()
    rng = np.random.default_rng(seed)
    means = rng.choice(blocks, size=(n, len(blocks)), replace=True).mean(axis=1)
    return float(blocks.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))
