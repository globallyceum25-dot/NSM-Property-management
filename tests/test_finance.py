"""Finance: entries, spreading over months, each property's result, and access."""

import datetime
import json

from server import access, db, finance

from .test_access import AccessTestCase


def entry(kind, category, amount, start, months=1, **extra):
    return dict({"kind": kind, "category": category, "amount": amount, "period_start": start, "months": months},
                **extra)


class SpreadTests(AccessTestCase):

    def test_a_years_rent_counts_a_twelfth_each_month(self):
        rows = [{"kind": "cost", "category": "RENT", "amount": 1200000, "period_start": "2026-04-01", "months": 12},
                {"kind": "capital", "category": "PURCHASE", "amount": 9000000, "period_start": "2026-05-01",
                 "months": 1}]
        months = finance.spread(rows, datetime.date(2026, 4, 1), datetime.date(2026, 6, 1))
        self.assertEqual(list(months), ["2026-04", "2026-05", "2026-06"])
        self.assertEqual([round(m["cost"]) for m in months.values()], [100000] * 3)
        self.assertEqual([round(m["rent"]) for m in months.values()], [100000] * 3)
        self.assertEqual(months["2026-05"]["capital"], 9000000)

    def test_verdicts(self):
        v = lambda income, cost: finance.verdict({"income": income, "cost": cost})  # noqa: E731
        self.assertEqual(v(0, 0), "none")
        self.assertEqual(v(0, 500), "cost-only")
        self.assertEqual(v(1000, 600), "profit")
        self.assertEqual(v(1000, 1030), "break-even")
        self.assertEqual(v(1000, 1500), "loss")


def monthly(kind, category, amounts, start=datetime.date(2025, 1, 1)):
    """One entry a month from `start`, with the given amounts."""
    rows = []
    for i, amount in enumerate(amounts):
        y, m = divmod(start.year * 12 + start.month - 1 + i, 12)
        rows.append({"kind": kind, "category": category, "amount": amount,
                     "period_start": datetime.date(y, m + 1, 1).isoformat(), "months": 1})
    return rows


class TrendTests(AccessTestCase):
    today = datetime.date(2026, 6, 15)          # history runs Jan 2025 - Jun 2026: 18 months
    last = datetime.date(2026, 6, 1)

    def test_a_loss_maker_that_is_improving_gets_a_break_even_month(self):
        rows = monthly("cost", "RENT", [100000] * 18) + monthly("income", "BUSINESS_REVENUE",
                                                                [20000 + 3000 * i for i in range(18)])
        t = finance.trend(rows, self.last, self.today)
        self.assertEqual((t["direction"], t["months"], t["confidence"]), ("up", 18, "high"))
        self.assertAlmostEqual(t["slope"], 3000, delta=1)
        self.assertLess(t["fitNow"], 0)
        self.assertEqual(t["breakEven"], "2027-04")       # -29,000 in Jun 2026, +3,000 a month -> 10 months
        self.assertIsNone(t["turnsLoss"])
        self.assertEqual(len(t["projection"]), finance.PROJECT_MONTHS)
        self.assertEqual(t["history"][-1]["avg3"], round(sum(r - 100000 for r in (65000, 68000, 71000)) / 3, 2))

    def test_a_profitable_property_slipping_could_turn_to_a_loss(self):
        rows = monthly("cost", "RENT", [100000] * 18) + monthly("income", "BUSINESS_REVENUE",
                                                                [200000 - 4000 * i for i in range(18)])
        t = finance.trend(rows, self.last, self.today)
        self.assertEqual(t["direction"], "down")
        self.assertEqual(t["turnsLoss"], "2027-02")        # +32,000 in Jun 2026, -4,000 a month -> 8 months
        self.assertIsNone(t["breakEven"])

    def test_steady_short_and_none(self):
        steady = monthly("cost", "RENT", [100000] * 12) + monthly("income", "BUSINESS_REVENUE", [150000] * 12)
        self.assertEqual(finance.trend(steady, self.last, self.today)["direction"], "flat")
        self.assertEqual(finance.trend(steady, self.last, self.today)["history"][-1]["month"], "2025-12")
        new = monthly("cost", "RENT", [1000] * 3, start=datetime.date(2026, 4, 1))
        short = finance.trend(new, self.last, self.today)
        self.assertEqual((short["direction"], short["months"], short["projection"]), ("short", 3, []))
        self.assertIsNone(finance.trend([], self.last, self.today))

    def test_months_not_yet_lived_are_left_out(self):
        rows = monthly("cost", "RENT", [100000] * 30)       # Jan 2025 to Jun 2027
        t = finance.trend(rows, datetime.date(2027, 3, 1), self.today)
        self.assertEqual(t["history"][-1]["month"], "2026-06")

    def test_the_reports_carry_the_trend(self):
        for i in range(8):
            month = "2026-%02d" % (i + 1)
            self.ok("POST", "/api/properties/1/finance", 201, data=entry("cost", "RENT", 100000, month))
            self.ok("POST", "/api/properties/1/finance", 201,
                    data=entry("income", "BUSINESS_REVENUE", 60000 + 8000 * i, month))
        mine = self.get("/api/properties/1/finance", **{"from": "2026-01", "to": "2026-08"})
        self.assertEqual(mine["trend"]["direction"], "up")
        row = next(p for p in self.get("/api/finance/summary", **{"from": "2026-01", "to": "2026-08"})["properties"]
                   if p["id"] == 1)
        self.assertEqual(row["trend"]["direction"], "up")
        self.assertEqual(len(row["trend"]["spark"]), 8)
        self.assertEqual(len(row["trend"]["history"]), 8)
        self.assertEqual(len(row["trend"]["projection"]), finance.PROJECT_MONTHS)
        portfolio = self.get("/api/finance/summary", **{"from": "2026-01", "to": "2026-08"})["trend"]
        self.assertEqual(portfolio["direction"], "up")


class EntryTests(AccessTestCase):

    def test_record_and_read_a_propertys_result(self):
        self.ok("POST", "/api/properties/1/finance", 201,
                data=entry("cost", "RENT", "1,200,000", "2026-04", 12, counterparty="Landowner"))
        self.ok("POST", "/api/properties/1/finance", 201, data=entry("income", "BUSINESS_REVENUE", 300000, "2026-04", 3))
        self.ok("POST", "/api/properties/1/finance", 201, data=entry("capital", "PURCHASE", 6000000, "2026-04", 12))
        mine = self.get("/api/properties/1/finance", **{"from": "2026-04", "to": "2026-06"})
        s = mine["summary"]
        self.assertEqual((s["income"], s["cost"], s["rent"], s["net"]), (300000, 300000, 300000, 0))
        self.assertEqual(s["status"], "break-even")
        self.assertEqual(s["capital"], 6000000)           # spent in the period, not counted as a running cost
        self.assertEqual(s["invested"], 6000000)
        self.assertEqual(len(mine["entries"]), 3)
        self.assertEqual(next(e for e in mine["entries"] if e["kind"] == "capital")["months"], 1)
        self.assertEqual(next(e for e in mine["entries"] if e["category"] == "RENT")["monthly"], 100000)

        report = self.get("/api/finance/summary", **{"from": "2026-04", "to": "2026-06"})
        row = next(p for p in report["properties"] if p["id"] == 1)
        self.assertEqual(row["net"], 0)
        self.assertEqual(report["totals"]["cost"], 300000)
        self.assertEqual(len(report["byMonth"]), 3)

    def test_profit_loss_and_return(self):
        self.ok("POST", "/api/properties/2/finance", 201, data=entry("income", "BUSINESS_REVENUE", 1200000, "2026-01", 12))
        self.ok("POST", "/api/properties/2/finance", 201, data=entry("cost", "MAINTENANCE", 240000, "2026-01", 12))
        self.ok("POST", "/api/properties/2/finance", 201, data=entry("capital", "PURCHASE", 4800000, "2025-06"))
        self.ok("POST", "/api/properties/3/finance", 201, data=entry("cost", "RENT", 600000, "2026-01", 12))
        self.ok("POST", "/api/properties/3/finance", 201, data=entry("income", "BUSINESS_REVENUE", 300000, "2026-01", 12))
        report = self.get("/api/finance/summary", **{"from": "2026-01", "to": "2026-12"})
        two = next(p for p in report["properties"] if p["id"] == 2)
        three = next(p for p in report["properties"] if p["id"] == 3)
        self.assertEqual((two["status"], two["net"], two["margin"]), ("profit", 960000, 80.0))
        self.assertEqual((two["returnPct"], two["paybackYears"]), (20.0, 5.0))
        self.assertEqual((three["status"], three["net"], three["rentShare"]), ("loss", -300000, 200.0))
        self.assertEqual(report["counts"]["loss"], 1)

    def test_bad_entries_are_refused(self):
        bad = [entry("cost", "BUSINESS_REVENUE", 100, "2026-04"),      # an income category as a cost
               entry("cost", "RENT", 0, "2026-04"),
               entry("cost", "RENT", "lots", "2026-04"),
               entry("cost", "RENT", 100, "not a month"),
               entry("cost", "RENT", 100, "2026-04", 500),
               entry("profit", "RENT", 100, "2026-04")]
        for body in bad:
            self.assertEqual(self.request("POST", "/api/properties/1/finance", data=body).status, 400, body)
        self.assertEqual(self.request("POST", "/api/properties/99999/finance",
                                      data=entry("cost", "RENT", 100, "2026-04")).status, 404)

    def test_edit_delete_and_the_audit_trail(self):
        made = self.ok("POST", "/api/properties/1/finance", 201, data=entry("cost", "UTILITIES", 25000, "2026-05"))
        changed = self.ok("PUT", "/api/finance/%d" % made["id"], data=entry("cost", "UTILITIES", 27500, "2026-05"))
        self.assertEqual(changed["amount"], 27500)
        self.ok("DELETE", "/api/finance/%d" % made["id"])
        self.assertEqual(self.request("DELETE", "/api/finance/%d" % made["id"]).status, 404)
        actions = [e["action"] for e in self.get("/api/audit", category="finance")["entries"]]
        self.assertTrue({"finance.create", "finance.update", "finance.delete"} <= set(actions))

    def test_deleting_a_property_removes_its_entries(self):
        self.ok("POST", "/api/properties/1/finance", 201, data=entry("cost", "RENT", 1000, "2026-05"))
        self.ok("DELETE", "/api/properties/1")
        conn = db.get_conn()
        left = conn.execute("SELECT COUNT(*) AS n FROM finance_entry WHERE property_id = 1").fetchone()["n"]
        db.release()
        self.assertEqual(left, 0)

    def test_export(self):
        self.ok("POST", "/api/properties/1/finance", 201, data=entry("cost", "RENT", 1000, "2026-05"))
        csv = self.request("GET", "/api/export/finance.csv", query={"from": "2026-05", "to": "2026-05"})
        self.assertEqual(csv.status, 200)
        text = csv.body.decode("utf-8-sig")
        self.assertIn("running_costs_lkr", text.splitlines()[0])
        self.assertIn("Cost only", text)


class FinanceAccessTests(AccessTestCase):

    def test_who_may_see_and_record(self):
        _, viewer = self.person("VIEWER")
        self.assertEqual(self.as_(viewer, "GET", "/api/finance/summary").status, 403)
        _, auditor = self.person("AUDITOR")
        self.assertEqual(self.as_(auditor, "GET", "/api/finance/summary").status, 200)
        self.assertEqual(self.as_(auditor, "POST", "/api/properties/1/finance",
                                  data=entry("cost", "RENT", 100, "2026-04")).status, 403)

    def test_a_manager_works_within_their_scope(self):
        sbu_id, mine, every = self.sample()
        other = next(p["id"] for p in every if p["id"] not in mine)
        _, cookie = self.person("PROPERTY_MANAGER", types=[sbu_id])
        report = self.as_(cookie, "GET", "/api/finance/summary").json()
        self.assertEqual({p["id"] for p in report["properties"]}, mine)
        self.assertEqual(self.as_(cookie, "POST", "/api/properties/%d/finance" % next(iter(mine)),
                                  data=entry("cost", "RENT", 100, "2026-04")).status, 201)
        self.assertEqual(self.as_(cookie, "POST", "/api/properties/%d/finance" % other,
                                  data=entry("cost", "RENT", 100, "2026-04")).status, 403)
        self.assertEqual(self.as_(cookie, "GET", "/api/properties/%d/finance" % other).status, 404)

    def test_a_register_set_up_before_finance_gets_the_new_actions_once(self):
        conn = db.get_conn()
        conn.execute("DELETE FROM app_role_permission WHERE permission LIKE 'finance.%'")
        conn.execute("UPDATE register_meta SET value = ? WHERE key = 'role_actions'",
                     (json.dumps(access.FIRST_ACTIONS),))
        conn.commit()
        access.seed_new_actions(conn)
        self.assertEqual(access.role_levels(conn, "ADMIN")["finance.view"], "yes")
        self.assertEqual(access.role_levels(conn, "PROPERTY_MANAGER")["finance.view"], "limited")
        # An administrator's later choice stays.
        conn.execute("DELETE FROM app_role_permission WHERE role_code = 'ADMIN' AND permission = 'finance.view'")
        conn.commit()
        access.seed_new_actions(conn)
        self.assertEqual(access.role_levels(conn, "ADMIN")["finance.view"], "no")
        db.release()
