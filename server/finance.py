"""Finance: what each property costs, what it earns, and whether it pays its way.

Every amount is an entry against one property, of one of three kinds:

    income   money the property brings in: business revenue earned at the
             site (school fees, sales), rent received, other income
    cost     what it takes to run: rent or lease paid, rates, maintenance,
             utilities, insurance, security, site staff
    capital  money invested in it: land or building purchase, construction,
             fit-out, legal and stamp duty

Income and running costs make the property's result for a period. Capital is
kept apart -- buying land is an investment, not a loss in the month it is paid --
and is set against the result as a return and a payback time.

An entry covers one or more whole months from its first month: a year's rent
paid in advance is one entry covering 12 months, and every report counts a
twelfth of it in each of those months.

Amounts are in Sri Lankan rupees. The financial year runs April to March.
"""

import csv
import datetime
import io
from typing import Any, Dict, List

from . import access, db
from .errors import ApiError

YEAR_START_MONTH = 4          # the financial year starts in April
MAX_MONTHS = 120

KINDS = [("income", "Income"), ("cost", "Running cost"), ("capital", "Capital")]

CATEGORIES = [
    ("BUSINESS_REVENUE", "income", "Business revenue", "What the business at this site earns, e.g. school fees"),
    ("RENT_RECEIVED", "income", "Rent received", "Rent paid to us by a tenant"),
    ("OTHER_INCOME", "income", "Other income", "Any other money the property brings in"),
    ("RENT", "cost", "Rent / lease", "Rent or lease payments to the landlord"),
    ("RATES_TAXES", "cost", "Rates & taxes", "Assessment rates and local taxes"),
    ("MAINTENANCE", "cost", "Maintenance & repairs", "Upkeep, repairs, servicing"),
    ("UTILITIES", "cost", "Utilities", "Electricity, water, telephone, internet"),
    ("INSURANCE", "cost", "Insurance", "Building and contents insurance"),
    ("SECURITY_CLEANING", "cost", "Security & cleaning", "Guards, cleaning, waste"),
    ("STAFF", "cost", "Site staff & admin", "Caretakers and site administration"),
    ("OTHER_COST", "cost", "Other running cost", "Any other cost of running the property"),
    ("PURCHASE", "capital", "Land / property purchase", "Buying the land or building"),
    ("CONSTRUCTION", "capital", "Construction & renovation", "Building work and major improvements"),
    ("FIT_OUT", "capital", "Equipment & fit-out", "Fixtures, furniture and equipment"),
    ("LEGAL_FEES", "capital", "Legal, stamp duty & fees", "Deeds, stamp duty, survey and legal fees"),
]
CATEGORY = {code: {"kind": kind, "label": label} for code, kind, label, _ in CATEGORIES}

# A property is "break-even" when its result is within this share of its turnover.
BREAK_EVEN_BAND = 0.05

FIELDS = ["kind", "category", "amount", "currency", "period_start", "months",
          "description", "counterparty", "reference_no", "notes"]


def reference():
    return {"kinds": [{"value": v, "label": label} for v, label in KINDS],
            "categories": [{"value": c, "kind": k, "label": label, "hint": hint} for c, k, label, hint in CATEGORIES],
            "yearStartMonth": YEAR_START_MONTH}


# --- months -----------------------------------------------------------------------

def _month(text, field):
    """'2026-04' or '2026-04-17' -> date(2026, 4, 1)."""
    try:
        parts = str(text or "").strip()[:7].split("-")
        return datetime.date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, IndexError):
        raise ApiError("Choose a month.", field=field) from None


def _add_months(day, n):
    y, m = divmod(day.year * 12 + day.month - 1 + n, 12)
    return datetime.date(y, m + 1, 1)


def _months_between(first, last):
    return (last.year - first.year) * 12 + last.month - first.month + 1


def _key(day):
    return day.strftime("%Y-%m")


def current_year_start(today=None):
    today = today or datetime.date.today()
    year = today.year if today.month >= YEAR_START_MONTH else today.year - 1
    return datetime.date(year, YEAR_START_MONTH, 1)


def period_from_query(q):
    """The months a report covers: ?from=YYYY-MM&to=YYYY-MM, or this financial
    year to date."""
    today = datetime.date.today()
    first = _month(q["from"], "from") if q.get("from") else current_year_start(today)
    last = _month(q["to"], "to") if q.get("to") else datetime.date(today.year, today.month, 1)
    if last < first:
        raise ApiError("The period ends before it starts.", field="to")
    if _months_between(first, last) > MAX_MONTHS:
        raise ApiError("Choose a period of up to ten years.", field="from")
    return first, last


# --- entries ----------------------------------------------------------------------

def _payload(ctx):
    data = ctx.json()
    kind = (data.get("kind") or "").strip()
    category = (data.get("category") or "").strip().upper()
    if kind not in dict(KINDS):
        raise ApiError("Choose income, running cost or capital.", field="kind")
    if category not in CATEGORY or CATEGORY[category]["kind"] != kind:
        raise ApiError("Choose a category.", field="category")
    try:
        amount = round(float(str(data.get("amount") or "").replace(",", "").strip()), 2)
    except ValueError:
        raise ApiError("Amount must be a number, for example 250,000.", field="amount") from None
    if amount <= 0:
        raise ApiError("Amount must be more than zero.", field="amount")
    if amount >= 1e13:
        raise ApiError("That amount is too large.", field="amount")
    try:
        months = int(data.get("months") or 1)
    except (TypeError, ValueError):
        raise ApiError("Months must be a whole number.", field="months") from None
    if kind == "capital":
        months = 1                       # an investment is not spread over months
    if not 1 <= months <= MAX_MONTHS:
        raise ApiError("An entry can cover 1 to 120 months.", field="months")
    clean = lambda key, limit: (str(data.get(key) or "").strip()[:limit] or None)  # noqa: E731
    return {
        "kind": kind, "category": category, "amount": amount, "currency": "LKR",
        "period_start": _month(data.get("period_start"), "period_start").isoformat(),
        "months": months,
        "description": clean("description", 200), "counterparty": clean("counterparty", 160),
        "reference_no": clean("reference_no", 80), "notes": clean("notes", 2000),
    }


def _entry_json(row):
    out = dict(row)
    start = datetime.date.fromisoformat(str(row["period_start"])[:10])
    out["period_start"] = _key(start)
    out["period_end"] = _key(_add_months(start, row["months"] - 1))
    out["monthly"] = round(row["amount"] / row["months"], 2)
    out["category_label"] = CATEGORY.get(row["category"], {}).get("label", row["category"])
    return out


def _property_or_404(ctx, conn, pid, key, write=False):
    row = conn.execute("SELECT id, property_code, name FROM property WHERE id = ?", (pid,)).fetchone()
    if row is None:
        raise ApiError("Property not found.", 404)
    access.check_property(ctx, conn, key, pid, write=write)
    return row


def _entry_or_404(ctx, conn, entry_id, key):
    row = conn.execute("SELECT * FROM finance_entry WHERE id = ?", (entry_id,)).fetchone()
    if row is None:
        raise ApiError("Entry not found.", 404)
    access.check_property(ctx, conn, key, row["property_id"], write=True)
    return row


def _audit(ctx, prop, payload, verb=""):
    ctx.audit_target = "%s · %s" % (prop["property_code"], prop["name"])
    ctx.audit_detail = "%s%s: LKR %s%s" % (
        verb, CATEGORY[payload["category"]]["label"], "{:,.2f}".format(payload["amount"]),
        " over %d months from %s" % (payload["months"], payload["period_start"][:7]) if payload["months"] > 1
        else " for %s" % payload["period_start"][:7])


def create_entry(ctx):
    conn = db.get_conn()
    pid = int(ctx.match.group("id"))
    prop = _property_or_404(ctx, conn, pid, "finance.create", write=True)
    payload = _payload(ctx)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload.update(property_id=pid, created_by=ctx.user["id"] if ctx.user else None,
                   created_at=stamp, updated_at=stamp)
    cols = ["property_id"] + FIELDS + ["created_by", "created_at", "updated_at"]
    new_id = conn.execute("INSERT INTO finance_entry (%s) VALUES (%s) RETURNING id"
                          % (", ".join(cols), ", ".join(":" + c for c in cols)), payload).fetchone()["id"]
    conn.commit()
    _audit(ctx, prop, payload)
    return 201, _entry_json(conn.execute("SELECT * FROM finance_entry WHERE id = ?", (new_id,)).fetchone())


def update_entry(ctx):
    conn = db.get_conn()
    entry_id = int(ctx.match.group("id"))
    old = _entry_or_404(ctx, conn, entry_id, "finance.edit")
    prop = _property_or_404(ctx, conn, old["property_id"], "finance.edit", write=True)
    payload = _payload(ctx)
    payload.update(id=entry_id, updated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    conn.execute("UPDATE finance_entry SET %s, updated_at = :updated_at WHERE id = :id"
                 % ", ".join("%s = :%s" % (c, c) for c in FIELDS), payload)
    conn.commit()
    _audit(ctx, prop, payload, "Now ")
    return 200, _entry_json(conn.execute("SELECT * FROM finance_entry WHERE id = ?", (entry_id,)).fetchone())


def delete_entry(ctx):
    conn = db.get_conn()
    entry_id = int(ctx.match.group("id"))
    old = _entry_or_404(ctx, conn, entry_id, "finance.delete")
    prop = conn.execute("SELECT property_code, name FROM property WHERE id = ?", (old["property_id"],)).fetchone()
    conn.execute("DELETE FROM finance_entry WHERE id = ?", (entry_id,))
    conn.commit()
    _audit(ctx, prop, dict(old), "Removed ")
    return 200, {"deleted": entry_id}


# --- reports ----------------------------------------------------------------------

def _empty():
    return {"income": 0.0, "cost": 0.0, "rent": 0.0, "capital": 0.0}


def spread(entries, first, last):
    """{month key: totals} for the months first..last, each entry counted in the
    months it covers (capital in the month it was spent)."""
    months = {}
    day = first
    while day <= last:
        months[_key(day)] = _empty()
        day = _add_months(day, 1)
    for e in entries:
        start = datetime.date.fromisoformat(str(e["period_start"])[:10])
        n = 1 if e["kind"] == "capital" else e["months"]
        share = e["amount"] / n
        for i in range(n):
            key = _key(_add_months(start, i))
            if key in months:
                months[key][e["kind"]] += share
                if e["category"] == "RENT":
                    months[key]["rent"] += share
    return months


def verdict(t):
    """What a property's figures say, in one word."""
    income, cost = t["income"], t["cost"]
    if not income and not cost:
        return "none"
    if not income:
        return "cost-only"
    net = income - cost
    if abs(net) <= BREAK_EVEN_BAND * max(income, cost):
        return "break-even"
    return "profit" if net > 0 else "loss"


def _finish(t):
    t = {k: round(v, 2) for k, v in t.items()}
    t["net"] = round(t["income"] - t["cost"], 2)
    t["margin"] = round(t["net"] / t["income"] * 100, 1) if t["income"] else None
    t["rentShare"] = round(t["rent"] / t["income"] * 100, 1) if t["income"] and t["rent"] else None
    t["status"] = verdict(t)
    return t


def _report(conn, where, params, first, last):
    """Per-property and portfolio totals for the months first..last."""
    from . import api
    props = conn.execute(api._PROPERTY_SELECT + (" WHERE " + " AND ".join(where) if where else ""), params).fetchall()
    ids = [p["id"] for p in props]
    entries: Dict[int, List[Any]] = {}
    if ids:
        end = _add_months(last, 1).isoformat()
        for chunk in range(0, len(ids), 500):
            part = ids[chunk:chunk + 500]
            for e in conn.execute(
                    "SELECT * FROM finance_entry WHERE property_id IN (%s) AND period_start < ?"
                    % ",".join("?" * len(part)), part + [end]).fetchall():
                entries.setdefault(e["property_id"], []).append(e)
    capital_all = {}
    if ids:
        for r in conn.execute("SELECT property_id, SUM(amount) AS n FROM finance_entry WHERE kind = 'capital' "
                              "GROUP BY property_id").fetchall():
            capital_all[r["property_id"]] = r["n"] or 0
    n_months = _months_between(first, last)
    portfolio_months = {k: _empty() for k in spread([], first, last)}
    rows = []
    for p in props:
        months = spread(entries.get(p["id"], []), first, last)
        total = _empty()
        for key, m in months.items():
            for k in total:
                total[k] += m[k]
                portfolio_months[key][k] += m[k]
        t = _finish(total)
        invested = round(capital_all.get(p["id"], 0), 2)
        yearly = t["net"] / n_months * 12
        rows.append(dict(t, id=p["id"], property_code=p["property_code"], name=p["name"],
                         sbu_name=p["sbu_name"], sbu_color=p["sbu_color"], sbu_id=p["sbu_id"],
                         entity_code=p["entity_code"], ownership_type=p["ownership_type"],
                         district=p["district"], invested=invested,
                         returnPct=round(yearly / invested * 100, 1) if invested and t["status"] != "none" else None,
                         paybackYears=round(invested / yearly, 1) if invested and yearly > 0 else None,
                         entries=len(entries.get(p["id"], []))))
    total = _empty()
    for m in portfolio_months.values():
        for k in total:
            total[k] += m[k]
    totals = _finish(total)
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("profit", "break-even", "loss", "cost-only", "none")}
    return {
        "period": {"from": _key(first), "to": _key(last), "months": n_months},
        "totals": totals, "counts": counts,
        "byMonth": [dict(month=k, **{x: round(v, 2) for x, v in m.items()}) for k, m in portfolio_months.items()],
        "properties": rows,
    }


def get_summary(ctx):
    """The portfolio's finance for a period, filtered like the property list."""
    from . import api
    conn = db.get_conn()
    first, last = period_from_query(ctx.query)
    where, params = api._property_filters(ctx.query)
    scope_where, scope_params = access.scope_for(ctx, "finance.view")
    return 200, _report(conn, where + scope_where, params + scope_params, first, last)


def property_finance(ctx):
    """One property: its figures for the period, month by month, and its entries."""
    conn = db.get_conn()
    pid = int(ctx.match.group("id"))
    _property_or_404(ctx, conn, pid, "finance.view")
    first, last = period_from_query(ctx.query)
    report = _report(conn, ["p.id = ?"], [pid], first, last)
    rows = conn.execute("""SELECT f.*, u.name AS created_by_name FROM finance_entry f
                           LEFT JOIN app_user u ON u.id = f.created_by
                           WHERE f.property_id = ? ORDER BY f.period_start DESC, f.id DESC""", (pid,)).fetchall()
    return 200, {"period": report["period"], "summary": report["properties"][0], "byMonth": report["byMonth"],
                 "entries": [_entry_json(r) for r in rows]}


def export_csv(ctx):
    from . import api
    conn = db.get_conn()
    first, last = period_from_query(ctx.query)
    where, params = api._property_filters(ctx.query)
    scope_where, scope_params = access.scope_for(ctx, "finance.export")
    report = _report(conn, where + scope_where, params + scope_params, first, last)
    labels = {"profit": "Profitable", "break-even": "Break-even", "loss": "Loss-making",
              "cost-only": "Cost only", "none": "No figures"}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["property_code", "property", "property_type", "owning_company", "tenure", "period_from", "period_to",
                "income_lkr", "running_costs_lkr", "of_which_rent_lkr", "net_lkr", "margin_pct", "status",
                "capital_invested_lkr", "return_pct_a_year", "payback_years"])
    for r in sorted(report["properties"], key=lambda r: r["net"]):
        w.writerow([r["property_code"], r["name"], r["sbu_name"], r["entity_code"] or "", r["ownership_type"],
                    report["period"]["from"], report["period"]["to"], r["income"], r["cost"], r["rent"], r["net"],
                    "" if r["margin"] is None else r["margin"], labels[r["status"]], r["invested"],
                    "" if r["returnPct"] is None else r["returnPct"],
                    "" if r["paybackYears"] is None else r["paybackYears"]])
    return 200, {"__raw__": True, "body": buf.getvalue().encode("utf-8-sig"),
                 "content_type": "text/csv; charset=utf-8", "inline": False,
                 "filename": "property-finance-%s-to-%s.csv" % (report["period"]["from"], report["period"]["to"])}


ROUTES = [
    ("GET", r"^/api/finance/summary$", get_summary),
    ("GET", r"^/api/export/finance\.csv$", export_csv),
    ("GET", r"^/api/properties/(?P<id>\d+)/finance$", property_finance),
    ("POST", r"^/api/properties/(?P<id>\d+)/finance$", create_entry),
    ("PUT", r"^/api/finance/(?P<id>\d+)$", update_entry),
    ("DELETE", r"^/api/finance/(?P<id>\d+)$", delete_entry),
]
