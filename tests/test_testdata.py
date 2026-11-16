"""Test data: loaded on request, kept apart from the real register."""

from server import db, storage, testdata

from .test_access import AccessTestCase


class TestDataTests(AccessTestCase):

    def setUp(self):
        super().setUp()
        self.mode(False)

    def tearDown(self):
        self.mode(False)
        super().tearDown()

    def mode(self, on, cookie=None):
        headers = {"Cookie": cookie} if cookie else None
        response = self.request("PUT", "/api/test-data/mode", data={"on": on}, headers=headers)
        self.assertEqual(response.status, 200, response.body)

    def test_loading_covers_every_section(self):
        made = self.ok("POST", "/api/test-data", 201)
        self.assertEqual(made["properties"], len(testdata.PROPERTIES))
        self.assertGreater(made["documents"], 40)
        self.assertGreater(made["entries"], 100)
        self.mode(True)
        props = self.get("/api/properties")
        self.assertEqual(len(props), len(testdata.PROPERTIES))
        self.assertTrue(all(p["property_code"].startswith(testdata.CODE_PREFIX) for p in props))
        self.assertEqual({p["sbu_id"] for p in props}, {s["id"] for s in self.get("/api/sbus")})
        self.assertEqual({p["status"] for p in props},
                         {"ACTIVE", "IDLE", "UNDER_CONSTRUCTION", "UNDER_DISPUTE", "DISPOSED"})
        self.assertTrue({"FREEHOLD", "LEASEHOLD", "RENTED_IN", "LEASED_OUT"} <= {p["ownership_type"] for p in props})
        stats = self.get("/api/stats")
        self.assertEqual(stats["totals"]["properties"], len(testdata.PROPERTIES))
        buckets = {r["bucket"] for r in stats["renewals"]} if "renewals" in stats else set()
        docs = self.get("/api/documents")
        self.assertTrue(docs["counts"]["expired"] and docs["counts"]["expiring"])
        self.assertTrue(docs["counts"]["file"] and docs["counts"]["nofile"])
        self.assertIsNotNone(buckets)
        finance = self.get("/api/finance/summary")
        for status in ("profit", "loss", "break-even", "cost-only"):
            self.assertTrue(finance["counts"][status], status)

    def test_real_and_test_data_never_mix(self):
        self.ok("POST", "/api/test-data", 201)
        real = self.get("/api/properties")
        self.assertEqual(len(real), 13)                         # the sample register only
        self.assertFalse(any(p["property_code"].startswith(testdata.CODE_PREFIX) for p in real))
        self.assertEqual(self.get("/api/stats")["totals"]["properties"], 13)
        self.assertEqual(self.get("/api/finance/summary")["totals"]["income"], 0)
        self.assertFalse(any("Test" in d["title"] or "—" in d["title"] for d in self.get("/api/documents")["documents"]
                             if d["property_code"].startswith(testdata.CODE_PREFIX)))
        csv = self.request("GET", "/api/export/properties.csv").body.decode("utf-8-sig")
        self.assertNotIn(testdata.CODE_PREFIX, csv)
        self.assertEqual(sum(s["property_count"] for s in self.get("/api/sbus")), 13)

        conn = db.get_conn()
        test_id = conn.execute("SELECT id FROM property WHERE is_test = 1").fetchone()["id"]
        db.release()
        self.assertEqual(self.request("GET", "/api/properties/%d" % test_id).status, 404)
        self.assertEqual(self.request("GET", "/api/properties/%d/finance" % test_id).status, 404)

        self.mode(True)
        self.assertEqual(self.request("GET", "/api/properties/%d" % test_id).status, 200)
        self.assertEqual(self.request("GET", "/api/properties/1").status, 404)    # a real one, now hidden
        self.assertEqual(sum(s["property_count"] for s in self.get("/api/sbus")), len(testdata.PROPERTIES))

    def test_what_you_add_in_test_mode_is_test_data(self):
        self.mode(True)
        sbu = self.get("/api/sbus")[0]["id"]
        made = self.ok("POST", "/api/properties", 201, data={
            "name": "Made while testing", "sbu_id": sbu, "ownership_type": "FREEHOLD", "status": "ACTIVE",
            "latitude": 6.9, "longitude": 79.86, "district": "Colombo"})
        self.mode(False)
        self.assertEqual(self.request("GET", "/api/properties/%d" % made["id"]).status, 404)
        self.assertNotIn(made["id"], {p["id"] for p in self.get("/api/properties")})

    def test_each_person_chooses_and_only_admins_load(self):
        self.ok("POST", "/api/test-data", 201)
        _, viewer = self.person("VIEWER")
        self.assertEqual(self.as_(viewer, "POST", "/api/test-data").status, 403)
        self.assertEqual(self.as_(viewer, "DELETE", "/api/test-data").status, 403)
        self.mode(True, viewer)
        self.assertEqual(len(self.as_(viewer, "GET", "/api/properties").json()), len(testdata.PROPERTIES))
        self.assertEqual(len(self.get("/api/properties")), 13)    # the admin still sees real data
        self.assertTrue(self.as_(viewer, "GET", "/api/auth/status").json()["user"]["testMode"])

    def test_removing_takes_documents_files_and_finance(self):
        self.ok("POST", "/api/test-data", 201)
        conn = db.get_conn()
        files = [r["stored_name"] for r in conn.execute(
            "SELECT d.stored_name FROM document d JOIN property p ON p.id = d.property_id "
            "WHERE p.is_test = 1 AND d.stored_name IS NOT NULL")]
        db.release()
        self.assertTrue(files and storage.load(files[0]))
        left = self.ok("DELETE", "/api/test-data")
        self.assertEqual(left, {"properties": 0, "documents": 0, "entries": 0})
        self.assertIsNone(storage.load(files[0]))
        self.assertEqual(len(self.get("/api/properties")), 13)
        actions = [e["action"] for e in self.get("/api/audit", category="property")["entries"]]
        self.assertTrue({"property.test_load", "property.test_remove"} <= set(actions))
