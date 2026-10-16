"""The JSON API end to end, over HTTP, on whichever database the run uses."""

import datetime

from server import db, storage

from .support import RegisterTestCase


def _days_from_today(days):
    today = datetime.datetime.now(datetime.timezone.utc).date()
    return (today + datetime.timedelta(days=days)).isoformat()


PDF = b"%PDF-1.4\n% test file\n" + b"x" * 4096


class ServingTests(RegisterTestCase):

    def test_app_shell_and_static_files(self):
        page = self.request("GET", "/")
        self.assertEqual(page.status, 200)
        self.assertIn("text/html", page.headers["Content-Type"])
        script = self.request("GET", "/js/app.js")
        self.assertEqual(script.status, 200)
        self.assertIn("javascript", script.headers["Content-Type"])
        # Unknown paths fall back to the app shell, which routes on the hash.
        self.assertEqual(self.request("GET", "/no/such/page").body, page.body)

    def test_unknown_endpoint_wrong_method_and_bad_json(self):
        self.assertEqual(self.request("GET", "/api/nothing").status, 404)
        self.assertEqual(self.request("PUT", "/api/sbus", data={}).status, 405)
        bad = self.request("POST", "/api/sbus", raw=b"{not json")
        self.assertEqual(bad.status, 400)
        self.assertIn("not valid JSON", bad.json()["error"])

    def test_reference_data(self):
        ref = self.get("/api/reference")
        self.assertIn("mapCenter", ref)
        self.assertEqual(len(ref["districts"]), 25)
        self.assertIn("DEED", [t["value"] for t in ref["documentTypes"]])


class SampleRegisterTests(RegisterTestCase):

    def test_sample_data(self):
        self.assertEqual(len(self.get("/api/properties")), 13)
        self.assertEqual(len(self.get("/api/sbus")), 8)
        self.assertEqual(len(self.get("/api/legal-entities")), 5)
        self.assertEqual(len(self.get("/api/locations")), 13)
        self.assertEqual(self.get("/api/documents")["counts"]["all"], 9)

    def test_one_property_with_its_documents(self):
        listed = {p["property_code"]: p for p in self.get("/api/properties")}
        head_office = self.get("/api/properties/%d" % listed["HO-COL-001"]["id"])
        self.assertEqual(head_office["has_deed"], 1)
        self.assertEqual(head_office["location_code"], "LCOL")
        self.assertEqual(head_office["entity_code"], "LIS")
        self.assertEqual(sorted(d["doc_type"] for d in head_office["documents"]),
                         ["DEED", "SURVEY_PLAN"])
        self.assertEqual(self.request("GET", "/api/properties/9999").status, 404)

    def test_search_ignores_case(self):
        lower = self.get("/api/properties", q="colombo")
        self.assertEqual(sorted(p["property_code"] for p in lower), ["HO-COL-001", "LOG-COL-001"])
        self.assertEqual(self.get("/api/properties", q="COLOMBO"), lower)
        docs = self.get("/api/documents", q="DEED OF TRANSFER")["documents"]
        self.assertEqual(len(docs), 3)

    def test_filters_split_the_register(self):
        with_deed = self.get("/api/properties", has_deed="1")
        without = self.get("/api/properties", has_deed="0")
        self.assertEqual(len(with_deed), 3)
        self.assertEqual(len(with_deed) + len(without), 13)
        no_company = self.get("/api/properties", legal_entity_id="none")
        self.assertTrue(all(p["legal_entity_id"] is None for p in no_company))
        self.assertEqual(len(no_company), 6)
        some_types = self.get("/api/sbus")[:2]
        ids = ",".join(str(t["id"]) for t in some_types)
        self.assertTrue(all(p["sbu_id"] in {t["id"] for t in some_types}
                            for p in self.get("/api/properties", sbu_id=ids)))

    def test_dashboard_agrees_with_the_list(self):
        for query in ({}, {"q": "a"}, {"has_deed": "0"}, {"legal_entity_id": "none"},
                      {"district": "Colombo"}, {"has_doc_type": "DEED"}):
            listed = self.get("/api/properties", **query)
            stats = self.get("/api/stats", **query)
            self.assertEqual(stats["totals"]["properties"], len(listed), query)
            self.assertEqual(sum(row["property_count"] for row in stats["bySbu"]), len(listed))
            self.assertEqual(sum(row["n"] for row in stats["byStatus"]), len(listed))
            self.assertEqual(sum(row["n"] for row in stats["byProvince"]), len(listed))
            self.assertEqual(stats["totals"]["allProperties"], 13)
            self.assertEqual(stats["filtered"], bool(query))
        self.assertEqual(self.get("/api/stats")["totals"]["without_deed"], 10)

    def test_documents_register(self):
        result = self.get("/api/documents")
        counts = result["counts"]
        self.assertEqual(counts["file"] + counts["nofile"], counts["all"])
        self.assertEqual(result["properties"], 7)
        everything = {d["id"] for d in result["documents"]}
        for sort in ("newest", "expiry", "title", "property", "sbu"):
            rows = self.get("/api/documents", sort=sort)["documents"]
            self.assertEqual({d["id"] for d in rows}, everything, sort)
        titles = [d["title"].lower() for d in self.get("/api/documents", sort="title")["documents"]]
        self.assertEqual(titles, sorted(titles))
        one = self.get("/api/documents/%d" % min(everything))
        self.assertIn("property_code", one)

    def test_csv_export(self):
        response = self.request("GET", "/api/export/properties.csv")
        self.assertEqual(response.status, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        lines = response.body.decode("utf-8-sig").splitlines()
        self.assertTrue(lines[0].startswith("property_code,name,property_type_code"))
        self.assertEqual(len(lines), 14)


class PropertyTypeAndCompanyTests(RegisterTestCase):

    def test_property_type_lifecycle(self):
        made = self.ok("POST", "/api/sbus", 201, data={"code": "zz", "name": "Test type",
                                                       "color": "#123456"})
        self.assertEqual(made["code"], "ZZ")
        clash = self.request("POST", "/api/sbus", data={"code": "ZZ", "name": "Again"})
        self.assertEqual(clash.status, 409)
        bad_colour = self.request("POST", "/api/sbus", data={"code": "YY", "name": "Y",
                                                             "color": "teal"})
        self.assertEqual((bad_colour.status, bad_colour.json()["field"]), (400, "color"))
        changed = self.ok("PUT", "/api/sbus/%d" % made["id"],
                          data={"code": "ZZ", "name": "Renamed", "color": "#654321"})
        self.assertEqual(changed["name"], "Renamed")
        self.assertGreaterEqual(changed["updated_at"], made["updated_at"])
        self.ok("DELETE", "/api/sbus/%d" % made["id"])
        self.assertEqual(len(self.get("/api/sbus")), 8)

    def test_a_type_in_use_cannot_be_deleted(self):
        used = max(self.get("/api/sbus"), key=lambda t: t["property_count"])
        self.assertGreater(used["property_count"], 0)
        self.assertEqual(self.request("DELETE", "/api/sbus/%d" % used["id"]).status, 409)

    def test_owning_company_lifecycle(self):
        made = self.ok("POST", "/api/legal-entities", 201,
                       data={"short_code": "tst", "name": "Test Co"})
        self.assertEqual(made["short_code"], "TST")
        self.assertEqual(self.request("POST", "/api/legal-entities",
                                      data={"short_code": "TST", "name": "x"}).status, 409)
        self.ok("PUT", "/api/legal-entities/%d" % made["id"],
                data={"short_code": "TST", "name": "Test Co Ltd"})
        self.ok("DELETE", "/api/legal-entities/%d" % made["id"])
        lis = [e for e in self.get("/api/legal-entities") if e["short_code"] == "LIS"][0]
        self.assertEqual(self.request("DELETE", "/api/legal-entities/%d" % lis["id"]).status, 409)


class PropertyTests(RegisterTestCase):

    def new_property(self, **overrides):
        sbu = self.ok("POST", "/api/sbus", 201, data={"code": "ZZ", "name": "Test type"})
        body = {"name": "Test property", "sbu_id": sbu["id"], "latitude": 6.9, "longitude": 79.9,
                "district": "Colombo", "extent_value": "1", "extent_unit": "ACRE",
                "building_area_value": "100", "building_area_unit": "PERCH",
                "acquisition_date": "2020-02-29", "acquisition_cost": "LKR 1,250,000/="}
        body.update(overrides)
        return self.ok("POST", "/api/properties", 201, data=body), body

    def test_create_read_update_delete(self):
        made, body = self.new_property()
        self.assertEqual(made["property_code"], "ZZ-0001")
        self.assertEqual(made["province"], "Western")
        self.assertEqual(made["extent_sqft"], 43560)
        self.assertEqual(made["building_area_sqft"], 27225)
        self.assertEqual(made["acquisition_cost"], 1250000)
        self.assertEqual(made["acquisition_date"], "2020-02-29")
        self.assertEqual((made["has_deed"], made["document_count"]), (0, 0))

        body.update(name="Renamed", status="IDLE", property_code="zz-custom")
        changed = self.ok("PUT", "/api/properties/%d" % made["id"], data=body)
        self.assertEqual((changed["name"], changed["status"], changed["property_code"]),
                         ("Renamed", "IDLE", "ZZ-CUSTOM"))
        self.assertEqual(len(self.get("/api/properties")), 14)

        self.ok("DELETE", "/api/properties/%d" % made["id"])
        self.assertEqual(self.request("GET", "/api/properties/%d" % made["id"]).status, 404)

    def test_property_codes_are_unique(self):
        made, body = self.new_property()
        body["property_code"] = "HO-COL-001"
        clash = self.request("PUT", "/api/properties/%d" % made["id"], data=body)
        self.assertEqual((clash.status, clash.json()["field"]), (409, "property_code"))

    def test_validation(self):
        sbu = self.get("/api/sbus")[0]["id"]
        cases = [
            ({"sbu_id": sbu, "latitude": 6.9, "longitude": 79.9}, "name"),
            ({"name": "x", "latitude": 6.9, "longitude": 79.9}, "sbu_id"),
            ({"name": "x", "sbu_id": sbu, "latitude": 51.5, "longitude": -0.1}, "latitude"),
            ({"name": "x", "sbu_id": sbu, "latitude": 6.9, "longitude": 79.9,
              "district": "Atlantis"}, "district"),
            ({"name": "x", "sbu_id": sbu, "latitude": 6.9, "longitude": 79.9,
              "acquisition_date": "29/02/2020"}, "acquisition_date"),
            ({"name": "x", "sbu_id": sbu, "latitude": 6.9, "longitude": 79.9,
              "extent_value": "-4"}, "extent_value"),
            ({"name": "x", "sbu_id": sbu, "latitude": 6.9, "longitude": 79.9,
              "status": "HAUNTED"}, "Status"),
        ]
        for body, field in cases:
            response = self.request("POST", "/api/properties", data=body)
            self.assertEqual((response.status, response.json()["field"]), (400, field), body)


class DocumentTests(RegisterTestCase):

    def setUp(self):
        super(DocumentTests, self).setUp()
        self.property = [p for p in self.get("/api/properties")
                         if p["property_code"] == "RET-GAL-002"][0]
        self.path = "/api/properties/%d/documents" % self.property["id"]

    def test_upload_download_delete(self):
        doc = self.ok("POST", self.path, 201,
                      data={"doc_type": "DEED", "title": "Test deed", "issue_date": "2020-03-01"},
                      files={"file": ("deed.pdf", PDF, "application/pdf")})
        self.assertEqual((doc["file_name"], doc["size_bytes"], doc["mime_type"]),
                         ("deed.pdf", len(PDF), "application/pdf"))
        download = self.request("GET", "/api/documents/%d/file" % doc["id"])
        self.assertEqual((download.status, download.body), (200, PDF))
        self.assertIn("inline", download.headers["Content-Disposition"])
        attachment = self.request("GET", "/api/documents/%d/file" % doc["id"],
                                  query={"disposition": "attachment"})
        self.assertIn("attachment", attachment.headers["Content-Disposition"])

        prop = self.get("/api/properties/%d" % self.property["id"])
        self.assertEqual((prop["has_deed"], prop["document_count"]), (1, 1))
        self.assertEqual(self.get("/api/documents")["counts"]["file"], 1)

        self.ok("DELETE", "/api/documents/%d" % doc["id"])
        self.assertEqual(self.request("GET", "/api/documents/%d/file" % doc["id"]).status, 404)
        self.assertIsNone(storage.load(doc["stored_name"]))

    def test_a_record_without_a_file(self):
        doc = self.ok("POST", self.path, 201, data={"doc_type": "OTHER"}, files={})
        self.assertEqual(doc["title"], "Other document")
        self.assertIsNone(doc["stored_name"])
        self.assertEqual(self.request("GET", "/api/documents/%d/file" % doc["id"]).status, 404)

    def test_rejected_uploads_leave_nothing_behind(self):
        cases = [
            ({"doc_type": "DEED", "issue_date": "2021-01-02", "expiry_date": "2020-01-01"},
             {"file": ("a.pdf", PDF, "application/pdf")}, "expiry_date"),
            ({"doc_type": "DEED"}, {"file": ("run.exe", b"MZ", "application/octet-stream")}, "file"),
            ({"doc_type": "DEED"}, {"file": ("empty.pdf", b"", "application/pdf")}, "file"),
            ({"doc_type": "NOT_A_TYPE"}, {}, "Document type"),
        ]
        for fields, files, field in cases:
            response = self.request("POST", self.path, data=fields, files=files)
            self.assertEqual((response.status, response.json()["field"]), (400, field), fields)
        self.assertEqual(self.get("/api/documents")["counts"]["all"], 9)
        self.assertEqual(self.request("POST", self.path, data={"doc_type": "OTHER"}).status, 400)

    def test_newest_photograph_becomes_the_cover(self):
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        first = self.ok("POST", self.path, 201, data={"doc_type": "PHOTOGRAPH"},
                        files={"file": ("a.png", png, "image/png")})
        second = self.ok("POST", self.path, 201, data={"doc_type": "PHOTOGRAPH"},
                         files={"file": ("b.png", png, "image/png")})
        self.assertGreater(second["id"], first["id"])
        prop = self.get("/api/properties/%d" % self.property["id"])
        self.assertEqual(prop["cover_document_id"], second["id"])

    def test_deleting_a_property_removes_its_files(self):
        doc = self.ok("POST", self.path, 201, data={"doc_type": "DEED"},
                      files={"file": ("deed.pdf", PDF, "application/pdf")})
        self.ok("DELETE", "/api/properties/%d" % self.property["id"])
        self.assertEqual(self.request("GET", "/api/documents/%d" % doc["id"]).status, 404)
        self.assertIsNone(storage.load(doc["stored_name"]))

    def test_renewal_ladder_and_expiry_lists(self):
        soon = self.ok("POST", self.path, 201, files={},
                       data={"doc_type": "LEASE_AGREEMENT", "expiry_date": _days_from_today(40)})
        lapsed = self.ok("POST", self.path, 201, files={},
                         data={"doc_type": "PERMIT_APPROVAL", "expiry_date": _days_from_today(-1)})
        pid = self.property["id"]

        self.assertIn(pid, [p["id"] for p in self.get("/api/properties", has_renewal="m3")])
        self.assertIn(pid, [p["id"] for p in self.get("/api/properties", has_renewal="expired")])
        self.assertNotIn(pid, [p["id"] for p in self.get("/api/properties", has_renewal="m6")])

        stats = self.get("/api/stats")
        self.assertIn(soon["id"], [d["id"] for d in stats["expiringSoon"]])
        self.assertNotIn(lapsed["id"], [d["id"] for d in stats["expiringSoon"]])
        renewals = {r["bucket"]: r["n"] for r in stats["renewals"]}
        self.assertEqual(list(renewals), ["expired", "m3", "m6", "m9", "m12", "later"])
        self.assertGreaterEqual(renewals["m3"], 1)
        self.assertGreaterEqual(renewals["expired"], 1)

        expiring = self.get("/api/documents", doc_status="expiring")["documents"]
        self.assertIn(soon["id"], [d["id"] for d in expiring])
        expired = self.get("/api/documents", doc_status="expired")["documents"]
        self.assertEqual([d["id"] for d in expired if d["property_id"] == pid], [lapsed["id"]])


class MasterSheetTests(RegisterTestCase):

    def test_every_sheet_loads(self):
        sheets = self.get("/api/masters")
        self.assertEqual(len(sheets), 11)
        for sheet in sheets:
            loaded = self.get("/api/masters/" + sheet["key"])
            self.assertEqual(len(loaded["rows"]), sheet["rowCount"], sheet["key"])
        self.assertEqual(self.request("GET", "/api/masters/nope").status, 404)
        self.assertEqual(self.request("POST", "/api/masters/district", data={}).status, 405)

    def test_location_and_code_lifecycle(self):
        place = self.ok("POST", "/api/masters/location", 201,
                        data={"name": "Test town", "district": "Galle", "latitude": "6.03"})
        self.assertEqual((place["province"], place["latitude"]), ("Southern", 6.03))
        code = self.ok("POST", "/api/masters/location_code", 201,
                       data={"code": "ltt", "location_id": place["id"]})
        self.assertEqual(code["code"], "LTT")
        clash = self.request("POST", "/api/masters/location_code",
                             data={"code": "LTT", "location_id": place["id"]})
        self.assertEqual(clash.status, 409)
        blocked = self.request("DELETE", "/api/masters/location/%d" % place["id"])
        self.assertEqual(blocked.status, 409)
        self.assertIn("1 location code", blocked.json()["error"])
        moved = self.ok("PUT", "/api/masters/location/%d" % place["id"],
                        data={"name": "Test town", "district": "Kandy"})
        self.assertEqual(moved["province"], "Central")
        self.ok("DELETE", "/api/masters/location_code/%d" % code["id"])
        self.ok("DELETE", "/api/masters/location/%d" % place["id"])

    def test_validation(self):
        missing = self.request("POST", "/api/masters/location_code", data={"code": "X"})
        self.assertEqual((missing.status, missing.json()["field"]), (400, "location_id"))
        ghost = self.request("POST", "/api/masters/location_code",
                             data={"code": "X", "location_id": 9999})
        self.assertEqual(ghost.status, 400)
        not_a_number = self.request("POST", "/api/masters/location",
                                    data={"name": "x", "latitude": "north"})
        self.assertEqual((not_a_number.status, not_a_number.json()["field"]), (400, "latitude"))


class DatabaseTests(RegisterTestCase):

    def test_batched_queries_match_single_ones(self):
        conn = db.get_conn()
        statements = [("SELECT COUNT(*) AS n FROM property WHERE sbu_id = ?", [sbu])
                      for sbu in range(1, 9)]
        batched = db.fetch_many(conn, statements)
        single = [conn.execute(sql, params).fetchall() for sql, params in statements]
        self.assertEqual([[dict(r) for r in rows] for rows in batched],
                         [[dict(r) for r in rows] for rows in single])
        self.assertEqual(sum(rows[0]["n"] for rows in batched), 13)
        db.release()

    def test_a_failed_query_does_not_break_the_next_request(self):
        if db.IS_POSTGRES:
            from psycopg import Error as DatabaseError
        else:
            from sqlite3 import Error as DatabaseError
        with self.assertRaises(DatabaseError):
            db.get_conn().execute("SELECT * FROM no_such_table")
        db.release()
        self.assertEqual(db.get_conn().execute("SELECT COUNT(*) AS n FROM property")
                         .fetchone()["n"], 13)
        db.release()
        self.assertEqual(len(self.get("/api/properties")), 13)
