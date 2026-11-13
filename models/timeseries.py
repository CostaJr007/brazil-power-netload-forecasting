"""Maths from earlier quant projects, rewritten for power-sector series.

- Ornstein-Uhlenbeck: the inflow anomaly reverts to the mean with half-life ln2/θ. Discretised, OU is an AR(1):
  a[t+h] = φ·a[t], with φ = exp(−θ·h).
- Kalman filter with innovation (Zollo & Weigel 2023): here the states are slowly changing regression coefficients.
  The normalised innovation (NIS) flags days when the model was surprised.
"""
import numpy as np


def ar_coefficient(x, y):
    """φ of y = φ·x by least squares without intercept (the anomaly already has mean ~0)."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    denominator = float(np.dot(x[valid], x[valid]))
    return float(np.dot(x[valid], y[valid]) / denominator) if denominator > 0 else 0.0


def ou_half_life(phi, horizon_days=1):
    """Half-life ln2/θ in days, with θ = −ln(φ)/h. Without mean reversion (φ outside (0,1)) returns NaN."""
    if not 0 < phi < 1:
        return float("nan")
    return float(np.log(2) / (-np.log(phi) / horizon_days))


def kalman_regression(X, y, horizon, r, q_ratio=1e-4, p0=1.0):
    """Regression with time-varying coefficients, predicting y[t] = value at t+horizon with data up to t.

    The coefficient is only updated with the pair (X[t−h], y[t−h]), because its answer only becomes
    known at t. This is what prevents look-ahead leakage.
    Returns (forecasts, NIS). NIS ~ chi-squared(1) when the model is well specified.
    """
    X, y = np.asarray(X, dtype=float), np.asarray(y, dtype=float)
    n, k = X.shape
    theta, P, Q = np.zeros(k), np.eye(k) * p0, np.eye(k) * q_ratio * r
    predictions, nis = np.full(n, np.nan), np.full(n, np.nan)
    known_x = np.isfinite(X).all(axis=1)
    for t in range(n):
        s = t - horizon
        if s >= 0 and known_x[s] and np.isfinite(y[s]):
            h = X[s]
            P = P + Q
            variance = float(h @ P @ h) + r
            innovation = y[s] - float(h @ theta)
            gain = P @ h / variance
            theta = theta + gain * innovation
            P = P - np.outer(gain, h @ P)
            nis[s] = innovation ** 2 / variance
        if known_x[t]:
            predictions[t] = float(X[t] @ theta)
    return predictions, nis
