"""Forecasting a monthly series -- a property's net result -- with ARIMA and
seasonal ARIMA (SARIMA), chosen automatically, with prediction ranges. Plain
Python: the register runs without third-party packages.

The procedure is the usual automatic ARIMA one (Hyndman & Khandakar, 2008):

1. A yearly pattern. With three years or more of figures, a classical
   decomposition (a centred 12-month moving average) measures how much of the
   month-to-month variation is a pattern that repeats every year -- the
   seasonal strength. A strong pattern (over 0.64) is removed by seasonal
   differencing (D = 1).
2. A drift. A KPSS test asks whether what is left still wanders away from a
   level (d = 1) or moves around one (d = 0).
3. The model. ARIMA(p,d,q)(P,D,Q)12 models with p, q <= 2 and P, Q <= 1 (and
   no more than four terms) are fitted by conditional sum of squares, searched
   stepwise: four starting models, then each neighbour of the best so far (one
   order up or down), until none has a lower AICc.
4. A check. The chosen model is refitted without the last months and asked to
   forecast them; so are two simple rivals: a straight-line trend, and
   repeating the last value (or the same month last year). If the straight line
   forecast those months better, it is used instead. The test's average miss is
   kept as the forecast's accuracy, and a Ljung-Box test asks whether what the
   model leaves unexplained is just noise.
5. The forecast. The model is run forward; its 80% and 95% ranges come from
   its psi weights, so they widen the further ahead they reach.

Fewer than MIN_ARIMA months are too few for ARIMA: a straight line is used,
with the ranges of a linear regression.
"""

import math
from collections import OrderedDict
from typing import Any, Dict, List, Optional

SEASON = 12
MIN_POINTS = 4                # fewer than this: no forecast at all
MIN_ARIMA = 12                # a year of figures before ARIMA is tried
MIN_SEASONAL = 36             # three years before a yearly pattern is looked for
SEASONAL_STRENGTH = 0.64      # stronger than this: seasonal differencing
KPSS_CRITICAL = 0.463         # 5% critical value, level stationarity
MAX_P, MAX_Q, MAX_TERMS = 2, 2, 4
Z80, Z95 = 1.2816, 1.96
SUBSCRIPT = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")  # SARIMA(...)(...)₁₂


def _mean(x):
    return sum(x) / len(x)


def _var(x):
    m = _mean(x)
    return sum((v - m) ** 2 for v in x) / len(x)


# --- polynomials in the backshift operator B: a list of coefficients by lag ----------

def _mul(a, b):
    out = [0.0] * (len(a) + len(b) - 1)
    for i, ai in enumerate(a):
        if ai:
            for j, bj in enumerate(b):
                out[i + j] += ai * bj
    return out


def _seasonal(coefs, s, sign):
    """1 + sign*c B^s for one seasonal coefficient (or 1 when there is none)."""
    return [1.0] + [0.0] * (s - 1) + [sign * coefs[0]] if coefs else [1.0]


def difference_operator(d, D, s=SEASON):
    op = [1.0]
    for _ in range(d):
        op = _mul(op, [1.0, -1.0])
    for _ in range(D):
        op = _mul(op, [1.0] + [0.0] * (s - 1) + [-1.0])
    return op


def difference(y, d, D, s=SEASON):
    """(1-B)^d (1-B^s)^D y."""
    op = difference_operator(d, D, s)
    k = len(op) - 1
    return [sum(op[j] * y[t - j] for j in range(k + 1)) for t in range(k, len(y))]


# --- tests --------------------------------------------------------------------------

def kpss(x):
    """KPSS statistic for level stationarity (Kwiatkowski et al., 1992), with a
    Newey-West long-run variance. Large values mean the series drifts."""
    n = len(x)
    m = _mean(x)
    e = [v - m for v in x]
    partial, s = [], 0.0
    for v in e:
        s += v
        partial.append(s)
    lags = int(4 * (n / 100.0) ** 0.25)
    lr = sum(v * v for v in e) / n
    for lag in range(1, lags + 1):
        lr += 2 * (1 - lag / (lags + 1.0)) * sum(e[t] * e[t - lag] for t in range(lag, n)) / n
    if lr <= 1e-12:
        return 0.0
    return sum(p * p for p in partial) / (n * n * lr)


def decompose(y, first_month, s=SEASON):
    """Classical additive decomposition: a centred moving-average trend, a
    seasonal index for each calendar month, and the seasonal strength
    max(0, 1 - Var(remainder) / Var(seasonal + remainder))."""
    n, h = len(y), s // 2
    trend: List[Optional[float]] = [None] * n
    for t in range(h, n - h):
        trend[t] = (0.5 * y[t - h] + sum(y[t - h + 1:t + h]) + 0.5 * y[t + h]) / s
    by_pos: Dict[int, List[float]] = {}
    for t in range(n):
        if trend[t] is not None:
            by_pos.setdefault(t % s, []).append(y[t] - trend[t])
    index = [_mean(by_pos[k]) if k in by_pos else 0.0 for k in range(s)]
    shift = _mean(index)
    index = [v - shift for v in index]
    detrended = [y[t] - trend[t] for t in range(n) if trend[t] is not None]
    remainder = [y[t] - trend[t] - index[t % s] for t in range(n) if trend[t] is not None]
    strength = 0.0
    if len(detrended) > 2 and _var(detrended) > 1e-12:
        strength = max(0.0, 1 - _var(remainder) / _var(detrended))
    # Index by calendar month (1-12) rather than by position in the series.
    months = {(first_month - 1 + k) % s + 1: round(index[k], 2) for k in range(s)}
    return {"strength": round(strength, 3), "indices": months}


def _gammaincc(a, x):
    """The regularised upper incomplete gamma function Q(a, x)."""
    if x <= 0:
        return 1.0
    lg = math.lgamma(a)
    if x < a + 1:                                   # series for P(a, x)
        term = total = 1.0 / a
        ap = a
        for _ in range(500):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-12:
                break
        return 1.0 - total * math.exp(-x + a * math.log(x) - lg)
    b, c, d = x + 1 - a, 1e300, 1.0 / (x + 1 - a)   # continued fraction for Q(a, x)
    f = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1.0 / d
        f *= d * c
        if abs(d * c - 1) < 1e-12:
            break
    return math.exp(-x + a * math.log(x) - lg) * f


def ljung_box(resid, lags, fitted):
    """Ljung-Box test that the residuals are white noise; returns the p-value."""
    n = len(resid)
    lags = min(lags, n - 1)
    if lags - fitted < 1 or n < 8:
        return None
    m = _mean(resid)
    e = [v - m for v in resid]
    denom = sum(v * v for v in e)
    if denom <= 1e-18:
        return 1.0
    q = 0.0
    for k in range(1, lags + 1):
        r = sum(e[t] * e[t - k] for t in range(k, n)) / denom
        q += r * r / (n - k)
    q *= n * (n + 2)
    return round(_gammaincc((lags - fitted) / 2.0, q / 2.0), 3)


# --- fitting ------------------------------------------------------------------------

def _nelder_mead(f, x0, step=0.1, iters=400, tol=1e-10):
    n = len(x0)
    if not n:
        return list(x0), f(x0)
    pts = [list(x0)] + [[x0[j] + (step if j == i else 0.0) for j in range(n)] for i in range(n)]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = sorted(range(n + 1), key=vals.__getitem__)
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        if abs(vals[-1] - vals[0]) <= tol * (abs(vals[0]) + tol):
            break
        cen = [sum(p[j] for p in pts[:-1]) / n for j in range(n)]
        worst = pts[-1]
        xr = [2 * cen[j] - worst[j] for j in range(n)]
        fr = f(xr)
        if fr < vals[0]:
            xe = [3 * cen[j] - 2 * worst[j] for j in range(n)]
            fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            outside = fr < vals[-1]
            xc = [cen[j] + 0.5 * ((xr[j] if outside else worst[j]) - cen[j]) for j in range(n)]
            fc = f(xc)
            if fc < min(fr, vals[-1]):
                pts[-1], vals[-1] = xc, fc
            else:
                best = pts[0]
                pts = [best] + [[best[j] + 0.5 * (p[j] - best[j]) for j in range(n)] for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
    i = min(range(n + 1), key=vals.__getitem__)
    return pts[i], vals[i]


def _stationary(c):
    """Is 1 - c1 B - c2 B^2 stationary (its roots outside the unit circle)?"""
    if not c:
        return True
    if len(c) == 1:
        return abs(c[0]) < 0.99
    return abs(c[1]) < 0.99 and c[1] + c[0] < 0.99 and c[1] - c[0] < 0.99


def _residuals(z, mu, ar, ma, start):
    """One-step errors of an ARMA model written as ar(B)(z - mu) = ma(B) e,
    conditional on the first `start` values (errors before them taken as 0)."""
    a = [(i, -c) for i, c in enumerate(ar) if i and c]
    b = [(j, c) for j, c in enumerate(ma) if j and c]
    w = [v - mu for v in z]
    e = [0.0] * len(z)
    sse = 0.0
    for t in range(start, len(z)):
        v = w[t]
        for i, c in a:
            v -= c * w[t - i]
        for j, c in b:
            if t - j >= 0:
                v -= c * e[t - j]
        e[t] = v
        sse += v * v
    return e, sse


def fit_arma(z, p, q, P, Q, mean, start, s=SEASON, fine=True):
    """Fit ARMA(p,q)(P,Q)s to z by conditional sum of squares; the estimates
    are kept stationary and invertible. `fine` adds a second, finer pass."""
    def unpack(x):
        return x[:p], x[p:p + q], x[p + q:p + q + P], x[p + q + P:p + q + P + Q], (x[-1] if mean else 0.0)

    def polys(x):
        phi, theta, sphi, stheta, _ = unpack(x)
        ar = _mul([1.0] + [-c for c in phi], _seasonal(sphi, s, -1.0))
        ma = _mul([1.0] + list(theta), _seasonal(stheta, s, 1.0))
        return ar, ma

    def cost(x):
        phi, theta, sphi, stheta, mu = unpack(x)
        if not (_stationary(phi) and _stationary([-c for c in theta])
                and all(abs(c) < 0.99 for c in sphi + stheta)):
            return 1e300
        ar, ma = polys(x)
        return _residuals(z, mu, ar, ma, start)[1]

    x0 = [0.0] * (p + q + P + Q) + ([_mean(z)] if mean else [])
    x, sse = _nelder_mead(cost, x0, iters=250, tol=1e-8)
    if fine:
        x, sse = _nelder_mead(cost, x, step=0.03)
    n_eff = len(z) - start
    k = p + q + P + Q + (1 if mean else 0) + 1             # + the noise variance
    sigma2 = max(sse / n_eff, 1e-12)
    loglik = -0.5 * n_eff * (math.log(2 * math.pi * sigma2) + 1)
    aic = -2 * loglik + 2 * k
    aicc = aic + 2 * k * (k + 1) / (n_eff - k - 1) if n_eff - k - 1 > 0 else math.inf
    phi, theta, sphi, stheta, mu = unpack(x)
    ar, ma = polys(x)
    e, _ = _residuals(z, mu, ar, ma, start)
    return {"p": p, "q": q, "P": P, "Q": Q, "mean": mean, "phi": phi, "theta": theta, "sphi": sphi,
            "stheta": stheta, "mu": mu, "ar": ar, "ma": ma, "sigma2": sigma2, "aicc": aicc, "e": e,
            "start": start, "k": k - 1}


def _arima_forecast(y, model, d, D, h, s=SEASON):
    """Run the model forward h months: the forecasts and their standard errors."""
    op = difference_operator(d, D, s)
    z = difference(y, d, D, s)
    ar, ma, mu = model["ar"], model["ma"], model["mu"]
    a = [(i, -c) for i, c in enumerate(ar) if i and c]
    b = [(j, c) for j, c in enumerate(ma) if j and c]
    zf, ef = list(z), list(model["e"])
    for t in range(len(z), len(z) + h):
        v = mu + sum(c * (zf[t - i] - mu) for i, c in a) + sum(c * ef[t - j] for j, c in b if t - j >= 0)
        zf.append(v)
        ef.append(0.0)
    yf = list(y)
    for i in range(h):
        t = len(y) + i
        yf.append(zf[len(z) + i] - sum(op[k] * yf[t - k] for k in range(1, len(op))))
    full = _mul(ar, op)                                  # differencing folded into the AR side
    psi = [1.0]
    for j in range(1, h):
        v = ma[j] if j < len(ma) else 0.0
        for i in range(1, min(j, len(full) - 1) + 1):
            v -= full[i] * psi[j - i]
        psi.append(v)
    se, total = [], 0.0
    for j in range(h):
        total += psi[j] ** 2
        se.append(math.sqrt(model["sigma2"] * total))
    return yf[len(y):], se


def auto_arima(y, first_month, s=SEASON):
    """Choose d, D and the orders as described above; None when too short."""
    n = len(y)
    D, strength, indices = 0, None, None
    if n >= MIN_SEASONAL:
        dec = decompose(y, first_month, s)
        strength, indices = dec["strength"], dec["indices"]
        if strength > SEASONAL_STRENGTH:
            D = 1
    d = 1 if kpss(difference(y, 0, D, s)) > KPSS_CRITICAL else 0
    z = difference(y, d, D, s)
    seasonal = n >= MIN_SEASONAL
    max_sp = 1 if seasonal and len(z) - (MAX_P + s) >= 20 else 0
    max_sq = 1 if seasonal else 0
    start = MAX_P + s * max_sp                     # every candidate conditions on the same months
    if len(z) - start < 8:
        return None
    mean = d + D <= 1                              # a mean (d + D = 0) or a drift (d + D = 1)
    limits = (MAX_P, MAX_Q, max_sp, max_sq)
    fitted: Dict[Any, Dict[str, Any]] = {}

    def allowed(o):
        return all(0 <= v <= hi for v, hi in zip(o, limits)) and sum(o) <= MAX_TERMS

    def try_(o):
        if o not in fitted:
            fitted[o] = fit_arma(z, o[0], o[1], o[2], o[3], mean, start, s, fine=False)
        return fitted[o]

    def better(a, b):
        # Ties (a perfect fit leaves nothing to choose by) go to the simpler model.
        return a["aicc"] < b["aicc"] - 1e-9 or (abs(a["aicc"] - b["aicc"]) <= 1e-9 and a["k"] < b["k"])

    best: Any = None
    at: Any = None
    o: Any
    for o in ((2, 2, 1, 1), (0, 0, 0, 0), (1, 0, 1, 0), (0, 1, 0, 1)):
        o = tuple(min(v, hi) for v, hi in zip(o, limits))
        while sum(o) > MAX_TERMS:                   # trim the largest starting model to fit
            o = (max(o[0] - 1, 0), o[1], o[2], o[3]) if o[0] >= o[1] else (o[0], o[1] - 1, o[2], o[3])
        m = try_(o)
        if best is None or better(m, best):
            best, at = m, o
    moved = True
    while moved:
        moved = False
        steps = [(i, v) for i in range(4) for v in (-1, 1)] + [("pq", v) for v in (-1, 1)]
        for i, v in steps:
            o = list(at)
            if i == "pq":
                o[0] += v
                o[1] += v
            else:
                o[i] += v
            o = tuple(o)
            if allowed(o):
                m = try_(o)
                if better(m, best):
                    best, at, moved = m, o, True
    best = fit_arma(z, at[0], at[1], at[2], at[3], mean, start, s)    # the winner, fitted carefully
    best.update(d=d, D=D, strength=strength, indices=indices, searched=len(fitted))
    return best


def _refit(y, chosen, s=SEASON):
    z = difference(y, chosen["d"], chosen["D"], s)
    if len(z) - chosen["start"] < 6:
        return None
    m = fit_arma(z, chosen["p"], chosen["q"], chosen["P"], chosen["Q"], chosen["mean"], chosen["start"], s)
    m.update(d=chosen["d"], D=chosen["D"])
    return m


def _line(y):
    n = len(y)
    mx, my = (n - 1) / 2.0, _mean(y)
    sxx = sum((x - mx) ** 2 for x in range(n)) or 1.0
    slope = sum((x - mx) * (v - my) for x, v in enumerate(y)) / sxx
    icpt = my - slope * mx
    resid = [v - (icpt + slope * x) for x, v in enumerate(y)]
    sigma2 = sum(r * r for r in resid) / max(1, n - 2)
    return icpt, slope, sigma2, sxx, mx


def _line_forecast(y, h):
    icpt, slope, sigma2, sxx, mx = _line(y)
    n = len(y)
    f = [icpt + slope * (n - 1 + i) for i in range(1, h + 1)]
    se = [math.sqrt(sigma2 * (1 + 1.0 / n + (n - 1 + i - mx) ** 2 / sxx)) for i in range(1, h + 1)]
    return f, se


def _label(m, s=SEASON):
    if m is None:
        return "Straight-line trend"
    base = "ARIMA(%d,%d,%d)" % (m["p"], m["d"], m["q"])
    if m["P"] or m["Q"] or m["D"]:
        return "S" + base + "(%d,%d,%d)%s" % (m["P"], m["D"], m["Q"], str(s).translate(SUBSCRIPT))
    return base


_cache: "OrderedDict[Any, Dict[str, Any]]" = OrderedDict()
_CACHE_SIZE = 1024


def forecast(values, first_month, horizon, s=SEASON):
    """Forecast `horizon` months after `values` (a monthly series whose first
    month is the calendar month `first_month`). Returns the model chosen, how
    well it forecast months it had not seen, and each month's forecast with
    80% and 95% ranges. Results are cached: the same figures give the same
    forecast, so only a property whose figures changed is fitted again."""
    key = (tuple(round(v, 2) for v in values), first_month, horizon, s)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    out = _forecast(list(values), first_month, horizon, s)
    _cache[key] = out
    if len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return out


def _forecast(values, first_month, horizon, s):
    n = len(values)
    if n < MIN_POINTS:
        return None
    # Work in units the optimiser likes; everything is scaled back at the end.
    scale = max(math.sqrt(_var(values)), _mean([abs(v) for v in values]), 1.0)
    y = [v / scale for v in values]

    model: Any = auto_arima(y, first_month, s) if n >= MIN_ARIMA else None
    test: Optional[Dict[str, Any]] = None
    use_line = model is None
    if model is not None:
        hold = 6 if n >= 24 else max(3, n // 4)
        train, actual = y[:-hold], y[-hold:]
        again = _refit(train, model, s)
        mae = lambda f: sum(abs(a - b) for a, b in zip(f, actual)) / hold * scale  # noqa: E731
        line_mae = mae(_line_forecast(train, hold)[0])
        seasonal_naive = model["D"] or model["P"] or model["Q"]
        naive = [train[len(train) - s + (i % s)] for i in range(hold)] if seasonal_naive and len(train) >= s \
            else [train[-1]] * hold
        test = {"months": hold, "lineMae": round(line_mae, 2), "naiveMae": round(mae(naive), 2),
                "naive": "the same month last year" if seasonal_naive and len(train) >= s else "last month's figure"}
        if again is not None:
            test["modelMae"] = round(mae(_arima_forecast(train, again, again["d"], again["D"], hold, s)[0]), 2)
            # The straight line is kept only when it clearly forecast the test months better.
            use_line = line_mae < test["modelMae"] * 0.9
        test["mae"] = test["lineMae"] if use_line else test.get("modelMae", test["lineMae"])

    if use_line:
        f, se = _line_forecast(y, horizon)
        icpt, slope, _, _, _ = _line(y)
        now = (icpt + slope * (n - 1)) * scale
        resid = [v - (icpt + slope * x) for x, v in enumerate(y)]
        lb = ljung_box(resid, 12 if n >= 24 else max(4, n // 3), 0)
    else:
        f, se = _arima_forecast(y, model, model["d"], model["D"], horizon, s)
        now = values[-1]
        resid = model["e"][model["start"]:]
        lb = ljung_box(resid, 24 if model["D"] or model["P"] or model["Q"] else 12, model["k"])

    seasonal = not use_line and bool(model["D"] or model["P"] or model["Q"])
    points = [{"net": round(v * scale, 2),
               "lo80": round((v - Z80 * e) * scale, 2), "hi80": round((v + Z80 * e) * scale, 2),
               "lo95": round((v - Z95 * e) * scale, 2), "hi95": round((v + Z95 * e) * scale, 2)}
              for v, e in zip(f, se)]
    # What break-even is judged on: with a yearly pattern, a month's result swings
    # with the season, so the level is the average of the 12 months to that point.
    if seasonal:
        series = list(values) + [p["net"] for p in points]
        levels = [_mean(series[n + i - s + 1:n + i + 1]) for i in range(horizon)]
        level_now = _mean(values[-s:])
    else:
        levels = [p["net"] for p in points]
        level_now = now
    info = {
        "method": "line" if use_line else ("sarima" if seasonal else "arima"),
        "label": _label(None if use_line else model, s),
        "order": None if use_line else [model["p"], model["d"], model["q"]],
        "seasonalOrder": None if use_line or not seasonal else [model["P"], model["D"], model["Q"], s],
        "coefficients": None if use_line else {
            k: [round(c, 3) for c in model[k]] for k in ("phi", "theta", "sphi", "stheta")},
        "aicc": None if use_line or not math.isfinite(model["aicc"]) else round(model["aicc"], 2),
        "sigma": round(math.sqrt(model["sigma2"]) * scale, 2) if not use_line else None,
        "seasonalStrength": model["strength"] if model else None,
        "seasonality": model["indices"] if model and model["strength"] is not None else None,
        "backtest": test,
        "ljungBoxP": lb,
        "whiteNoise": None if lb is None else lb >= 0.05,
        "months": n,
        "searched": None if use_line else model.get("searched"),
        "differencing": None if use_line else {"d": model["d"], "D": model["D"]},
    }
    if info["seasonality"]:
        info["seasonality"] = {m: round(v * scale, 2) for m, v in info["seasonality"].items()}
    return {"model": info, "points": points, "now": round(now, 2), "levels": levels, "levelNow": level_now}
