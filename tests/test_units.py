"""Small pure functions: SQL translation, value conversion, date arithmetic."""

import datetime
import decimal
import unittest

from server import api, db, srilanka


class PostgresSqlTests(unittest.TestCase):

    def test_placeholders(self):
        self.assertEqual(db._pg_sql("SELECT * FROM t WHERE a = ? AND b IN (?, ?)"),
                         "SELECT * FROM t WHERE a = %s AND b IN (%s, %s)")
        self.assertEqual(db._pg_sql("UPDATE t SET name = :name WHERE id = :id"),
                         "UPDATE t SET name = %(name)s WHERE id = %(id)s")

    def test_casts_strings_and_comments_are_left_alone(self):
        self.assertEqual(db._pg_sql("SELECT x::text, 'a?b :c' FROM t"),
                         "SELECT x::text, 'a?b :c' FROM t")
        self.assertEqual(db._pg_sql("SELECT 'it''s ?' AS q, ?"), "SELECT 'it''s ?' AS q, %s")
        self.assertEqual(db._pg_sql("SELECT 1 -- what? :x\n, ?"), "SELECT 1 -- what? :x\n, %s")

    def test_literal_percent_signs_are_doubled(self):
        self.assertEqual(db._pg_sql("WHERE mime LIKE 'image/%' AND n % 2 = ?"),
                         "WHERE mime LIKE 'image/%%' AND n %% 2 = %s")
        self.assertEqual(db._pg_sql("-- 100% sure\nSELECT 1"), "-- 100%% sure\nSELECT 1")


class PlainValueTests(unittest.TestCase):
    """Postgres values come back exactly as the SQLite register returned them."""

    def test_conversions(self):
        utc = datetime.timezone.utc
        colombo = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        self.assertEqual(db._plain(True), 1)
        self.assertEqual(db._plain(False), 0)
        self.assertEqual(db._plain(datetime.date(2026, 2, 3)), "2026-02-03")
        self.assertEqual(db._plain(datetime.datetime(2026, 2, 3, 4, 5, 6, 789, tzinfo=utc)),
                         "2026-02-03 04:05:06")
        self.assertEqual(db._plain(datetime.datetime(2026, 2, 3, 9, 35, 6, tzinfo=colombo)),
                         "2026-02-03 04:05:06")
        self.assertEqual(db._plain(decimal.Decimal("1.5")), 1.5)
        for unchanged in (None, 7, 2.5, "text"):
            self.assertEqual(db._plain(unchanged), unchanged)


class DateTests(unittest.TestCase):

    def test_months_land_on_the_last_day_when_needed(self):
        jan31 = datetime.date(2026, 1, 31)
        self.assertEqual(api._date_sql(today=jan31), "'2026-01-31'")
        self.assertEqual(api._date_sql(months=1, today=jan31), "'2026-02-28'")
        self.assertEqual(api._date_sql(months=3, today=jan31), "'2026-04-30'")
        self.assertEqual(api._date_sql(months=12, today=jan31), "'2027-01-31'")
        self.assertEqual(api._date_sql(months=13, today=jan31), "'2027-02-28'")
        self.assertEqual(api._date_sql(months=1, today=datetime.date(2028, 1, 31)), "'2028-02-29'")
        self.assertEqual(api._date_sql(months=3, today=datetime.date(2026, 11, 15)), "'2027-02-15'")

    def test_days(self):
        self.assertEqual(api._date_sql(days=180, today=datetime.date(2026, 10, 16)), "'2027-04-14'")

    def test_renewal_edges_are_in_order(self):
        edges = api._renewal_edges()
        self.assertEqual(edges, sorted(edges))
        self.assertEqual(len(set(edges)), 5)


class AreaTests(unittest.TestCase):

    def test_square_feet(self):
        self.assertEqual(srilanka.to_sqft(1, "ACRE"), 43560)
        self.assertEqual(srilanka.to_sqft(1, "PERCH"), 272.25)
        self.assertEqual(srilanka.to_sqft(1, "ROOD"), 40 * 272.25)
        self.assertIsNone(srilanka.to_sqft(None, "ACRE"))
