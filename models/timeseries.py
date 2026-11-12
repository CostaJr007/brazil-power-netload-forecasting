"""Maths from earlier quant projects, rewritten for power-sector series.

- Ornstein-Uhlenbeck: the inflow anomaly reverts to the mean with half-life ln2/θ. Discretised, OU is an AR(1):
  a[t+h] = φ·a[t], with φ = exp(−θ·h).
- Kalman filter with innovation (Zollo & Weigel 2023): here the states are slowly changing regression coefficients.
  The normalised innovation (NIS) flags days when the model was surprised.
"""
import numpy as np


def ar_coefficient(x, y):
    """φ de y = φ·x por mínimos quadrados sem intercepto (a anomalia já tem média ~0)."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    denominator = float(np.dot(x[valid], x[valid]))
    return float(np.dot(x[valid], y[valid]) / denominator) if denominator > 0 else 0.0


def ou_half_life(phi, horizon_days=1):
    """Meia-vida ln2/θ em dias, com θ = −ln(φ)/h. Sem reversão à média (φ fora de (0,1)) devolve NaN."""
    if not 0 < phi < 1:
        return float("nan")
    return float(np.log(2) / (-np.log(phi) / horizon_days))


def kalman_regression(X, y, horizon, r, q_ratio=1e-4, p0=1.0):
    """Regressão com coeficientes variáveis, prevendo y[t] = valor em t+horizon com dados até t.

    O coeficiente só é atualizado com o par (X[t−h], y[t−h]), porque a resposta dele só
    fica conhecida em t. Essa é a parte que impede vazamento do futuro.
    Devolve (previsões, NIS). NIS ~ qui-quadrado(1) quando o modelo está bem especificado.
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
