"""Starter lists are given once: a list emptied on purpose stays empty."""

from server import db

from .support import RegisterTestCase


class StarterListTests(RegisterTestCase):

    def test_emptied_lists_are_not_refilled_on_restart(self):
        # Clear the register the way someone would from the app.
        for prop in self.get("/api/properties"):
            self.ok("DELETE", "/api/properties/%d" % prop["id"])
        for code in self.get("/api/masters/location_code")["rows"]:
            self.ok("DELETE", "/api/masters/location_code/%d" % code["id"])
        for place in self.get("/api/masters/location")["rows"]:
            self.ok("DELETE", "/api/masters/location/%d" % place["id"])
        for company in self.get("/api/legal-entities"):
            self.ok("DELETE", "/api/legal-entities/%d" % company["id"])

        db.init_db()          # what the next start does
        db.release()

        self.assertEqual(self.get("/api/legal-entities"), [])
        self.assertEqual(self.get("/api/masters/location")["rows"], [])
        self.assertEqual(self.get("/api/masters/location_code")["rows"], [])
        self.assertEqual(self.get("/api/properties"), [])
        # Property types are untouched.
        self.assertEqual(len(self.get("/api/sbus")), 8)
