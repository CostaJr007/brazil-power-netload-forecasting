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
    """Returns (start, exclusive_end) for each test year, cutting the last one at last_date."""
    last = pd.Timestamp(last_date)
    folds = []
    for year in range(first_year, last.year + 1):
        start, end = pd.Timestamp(year, 1, 1), pd.Timestamp(year + 1, 1, 1)
        folds.append((start, min(end, last + pd.Timedelta(days=1))))
    return folds


def train_cutoff(start, gap):
    """Exclusive end of the training rows for a fold whose first test day is `start`.

    When day `start` is forecast, verified data only reach start−gap, so later targets are not known yet.
    Training on rows dated < start−(gap−1) keeps a fold boundary from leaking one or two days of the future.
    """
    return pd.Timestamp(start) - pd.Timedelta(days=gap - 1)


def placebo_shift(series, days=730):
    """Shift the series by 2 years: keeps seasonality and destroys that day's real-time information."""
    return series.shift(days)


def mae(y, pred):
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(pred))))


def skill(mae_model, mae_baseline):
    """Share of the baseline error removed: 0 ties, 1 is perfect, negative is worse than the baseline."""
    return 1.0 - mae_model / mae_baseline


def block_bootstrap_diff(dates, abs_err_a, abs_err_b, block_days=14, n=2000, seed=0):
    """95% CI of MAE(a) − MAE(b). Blocks preserve the autocorrelation of errors, which a simple resample would ignore."""
    frame = pd.DataFrame({"d": pd.to_datetime(dates), "x": np.asarray(abs_err_a) - np.asarray(abs_err_b)})
    daily = frame.groupby("d")["x"].mean()
    blocks = daily.groupby((daily.index - daily.index[0]).days // block_days).mean().to_numpy()
    rng = np.random.default_rng(seed)
    means = rng.choice(blocks, size=(n, len(blocks)), replace=True).mean(axis=1)
    return float(blocks.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))
