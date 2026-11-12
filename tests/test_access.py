"""Roles, permissions, data scope, user administration and the audit log."""

import re
import uuid

from server import access, api, auth, db

from .support import RegisterTestCase, TEST_EMAIL

PASSWORD = "a long enough password"


def reset_roles():
    """Back to the workbook's roles, whatever an earlier test changed."""
    conn = db.get_conn()
    conn.execute("DELETE FROM app_role_permission")
    conn.execute("DELETE FROM app_role")
    conn.execute("DELETE FROM register_meta WHERE key = 'roles'")
    conn.commit()
    access.seed_roles(conn)
    db.release()


class AccessTestCase(RegisterTestCase):

    def setUp(self):
        super().setUp()
        reset_roles()

    def person(self, role, types=(), companies=(), password=PASSWORD):
        """A new account with this role and scope, signed in; returns (id, cookie)."""
        email = "p-%s@example.lk" % uuid.uuid4().hex[:8]
        conn = db.get_conn()
        user_id = auth.create_user(conn, email, "Person %s" % role.title(), role, password)
        for kind, ids in (("type", types), ("company", companies)):
            for ref in ids:
                conn.execute("INSERT INTO app_user_scope (user_id, kind, ref_id) VALUES (?, ?, ?)",
                             (user_id, kind, ref))
        conn.commit()
        db.release()
        response = self.request("POST", "/api/auth/login", anonymous=True,
                                data={"email": email, "password": password})
        self.assertEqual(response.status, 200, response.body)
        return user_id, response.headers["Set-Cookie"].split(";")[0]

    def as_(self, cookie, method, path, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {}, Cookie=cookie)
        return self.request(method, path, headers=headers, **kwargs)

    def sample(self):
        """(a property type id, the ids of its properties, every property)."""
        props = self.get("/api/properties")
        sbu_id = props[0]["sbu_id"]
        return sbu_id, {p["id"] for p in props if p["sbu_id"] == sbu_id}, props


class RulesTests(AccessTestCase):

    def test_every_route_has_an_access_rule(self):
        missing = [access.handler_key(h) for _, _, h in api.ROUTES
                   if access.handler_key(h) not in access.ROUTE_PERMISSIONS]
        self.assertEqual(missing, [])
        stale = set(access.ROUTE_PERMISSIONS) - {access.handler_key(h) for _, _, h in api.ROUTES}
        self.assertEqual(stale, set())

    def test_roles_start_as_the_workbook_says(self):
        conn = db.get_conn()
        officer = access.role_levels(conn, "PROPERTY_OFFICER")
        viewer = access.role_levels(conn, "VIEWER")
        admin = access.role_levels(conn, "ADMIN")
        db.release()
        self.assertEqual((officer["properties.view"], officer["properties.create"], officer["properties.delete"]),
                         ("limited", "yes", "no"))
        self.assertEqual((viewer["documents.view"], viewer["documents.download"]), ("yes", "no"))
        self.assertEqual((admin["users.create"], admin["roles.manage"], admin["types.delete"]),
                         ("limited", "no", "no"))
        self.assertEqual(len(access.ALL_KEYS), 34)

    def test_status_carries_permissions_and_scope(self):
        _, cookie = self.person("VIEWER")
        status = self.as_(cookie, "GET", "/api/auth/status").json()
        self.assertEqual(status["access"]["permissions"]["properties.create"], "no")
        self.assertEqual(status["access"]["scope"], {"types": [], "companies": []})


class ViewerTests(AccessTestCase):

    def test_a_viewer_reads_but_changes_nothing(self):
        _, cookie = self.person("VIEWER")
        props = self.as_(cookie, "GET", "/api/properties")
        self.assertEqual(props.status, 200)
        self.assertEqual(len(props.json()), 13)
        self.assertEqual(self.as_(cookie, "GET", "/api/stats").status, 200)
        refused = [
            ("POST", "/api/properties", {"name": "X"}),
            ("DELETE", "/api/properties/1", None),
            ("POST", "/api/sbus", {"code": "X", "name": "X"}),
            ("GET", "/api/export/properties.csv", None),
            ("GET", "/api/import/template.xlsx", None),
            ("GET", "/api/users", None),
            ("GET", "/api/audit", None),
            ("POST", "/api/masters/location", {"name": "X"}),
        ]
        for method, path, data in refused:
            self.assertEqual(self.as_(cookie, method, path, data=data).status, 403, (method, path))
        doc = self.get("/api/documents")["documents"][0]
        self.assertEqual(self.as_(cookie, "GET", "/api/documents/%d" % doc["id"]).status, 200)
        self.assertEqual(self.as_(cookie, "GET", "/api/documents/%d/file" % doc["id"]).status, 403)


class ScopeTests(AccessTestCase):

    def test_a_property_officer_sees_and_edits_only_their_scope(self):
        sbu_id, mine, every = self.sample()
        other = next(p for p in every if p["id"] not in mine)
        _, cookie = self.person("PROPERTY_OFFICER", types=[sbu_id])

        seen = {p["id"] for p in self.as_(cookie, "GET", "/api/properties").json()}
        self.assertEqual(seen, mine)
        self.assertEqual(self.as_(cookie, "GET", "/api/stats").json()["totals"]["properties"], len(mine))
        self.assertEqual(self.as_(cookie, "GET", "/api/properties/%d" % other["id"]).status, 404)
        docs = self.as_(cookie, "GET", "/api/documents").json()["documents"]
        self.assertTrue(all(d["sbu_id"] == sbu_id for d in docs))

        own = self.get("/api/properties/%d" % next(iter(mine)))
        body = {k: own[k] for k in ("name", "sbu_id", "legal_entity_id", "location_id", "latitude",
                                    "longitude", "ownership_type", "status", "district")}
        self.assertEqual(self.as_(cookie, "PUT", "/api/properties/%d" % own["id"],
                                  data=dict(body, name="Renamed")).status, 200)
        moved = self.as_(cookie, "PUT", "/api/properties/%d" % own["id"],
                         data=dict(body, sbu_id=other["sbu_id"]))
        self.assertEqual(moved.status, 403)
        theirs = self.as_(cookie, "PUT", "/api/properties/%d" % other["id"],
                          data=dict(body, sbu_id=other["sbu_id"]))
        self.assertEqual(theirs.status, 403)

    def test_no_scope_means_nothing_in_limited_areas(self):
        _, cookie = self.person("PROPERTY_OFFICER")
        self.assertEqual(self.as_(cookie, "GET", "/api/properties").json(), [])

    def test_limited_export_holds_only_the_scope(self):
        sbu_id, mine, _ = self.sample()
        _, cookie = self.person("PROPERTY_MANAGER", types=[sbu_id])
        csv = self.as_(cookie, "GET", "/api/export/properties.csv").body.decode("utf-8-sig")
        self.assertEqual(len(csv.strip().splitlines()) - 1, len(mine))

    def test_limited_document_delete_is_for_your_own_uploads(self):
        _, cookie = self.person("DOCUMENT_CONTROLLER")
        existing = self.get("/api/documents")["documents"][0]
        self.assertEqual(self.as_(cookie, "DELETE", "/api/documents/%d" % existing["id"]).status, 403)
        made = self.as_(cookie, "POST", "/api/properties/1/documents",
                        data={"doc_type": "OTHER", "title": "Site photo note"}, files={})
        self.assertEqual(made.status, 201, made.body)
        self.assertEqual(self.as_(cookie, "DELETE", "/api/documents/%d" % made.json()["id"]).status, 200)


class UserAdminTests(AccessTestCase):

    def test_new_person_gets_a_temporary_password_they_must_change(self):
        sbu_id, _, _ = self.sample()
        made = self.ok("POST", "/api/users", 201, data={
            "name": "Nimal Silva", "email": "nimal-%s@example.lk" % uuid.uuid4().hex[:6],
            "role": "PROPERTY_OFFICER", "scope": {"types": [sbu_id], "companies": []}})
        temp = made["temporaryPassword"]
        self.assertTrue(made["user"]["mustChangePassword"])
        self.assertEqual(made["user"]["scope"]["types"], [sbu_id])

        login = self.request("POST", "/api/auth/login", anonymous=True,
                             data={"email": made["user"]["email"], "password": temp})
        self.assertTrue(login.json()["user"]["mustChangePassword"])
        cookie = login.headers["Set-Cookie"].split(";")[0]
        blocked = self.as_(cookie, "GET", "/api/properties")
        self.assertEqual(blocked.status, 403)
        self.assertTrue(blocked.json()["changePassword"])

        wrong = self.as_(cookie, "POST", "/api/account/password",
                         data={"current": "nope", "password": PASSWORD, "confirm": PASSWORD})
        self.assertEqual(wrong.status, 400)
        changed = self.as_(cookie, "POST", "/api/account/password",
                           data={"current": temp, "password": PASSWORD, "confirm": PASSWORD})
        self.assertEqual(changed.status, 200, changed.body)
        self.assertEqual(self.as_(cookie, "GET", "/api/properties").status, 200)   # same session lives on

    def test_an_administrator_cannot_create_or_change_super_admins(self):
        _, cookie = self.person("ADMIN")
        new = {"name": "X", "email": "x-%s@example.lk" % uuid.uuid4().hex[:6], "scope": {}}
        self.assertEqual(self.as_(cookie, "POST", "/api/users", data=dict(new, role="SUPER_ADMIN")).status, 403)
        self.assertEqual(self.as_(cookie, "POST", "/api/users", data=dict(new, role="VIEWER")).status, 201)
        boss = next(u for u in self.get("/api/users")["users"] if u["email"] == TEST_EMAIL)
        self.assertEqual(self.as_(cookie, "PUT", "/api/users/%d" % boss["id"], data={"name": "Y"}).status, 403)
        self.assertEqual(self.as_(cookie, "PUT", "/api/users/%d" % boss["id"],
                                  data={"isActive": False}).status, 403)
        self.assertEqual(self.as_(cookie, "POST", "/api/users/%d/reset-password" % boss["id"]).status, 403)
        roles = self.as_(cookie, "GET", "/api/roles").json()
        self.assertNotIn("SUPER_ADMIN", roles["assignable"])
        self.assertFalse(roles["canManage"])

    def test_no_one_locks_the_register_out(self):
        me = next(u for u in self.get("/api/users")["users"] if u["isYou"])
        self.assertEqual(self.request("PUT", "/api/users/%d" % me["id"], data={"isActive": False}).status, 400)
        self.assertEqual(self.request("PUT", "/api/users/%d" % me["id"], data={"role": "VIEWER"}).status, 400)

    def test_switching_someone_off_signs_them_out(self):
        user_id, cookie = self.person("VIEWER")
        self.ok("PUT", "/api/users/%d" % user_id, data={"isActive": False})
        self.assertEqual(self.as_(cookie, "GET", "/api/properties").status, 401)
        self.ok("PUT", "/api/users/%d" % user_id, data={"isActive": True})

    def test_a_password_reset_issues_a_new_temporary_password(self):
        user_id, cookie = self.person("VIEWER")
        reset = self.ok("POST", "/api/users/%d/reset-password" % user_id)
        self.assertTrue(re.match(r"^\S{4}-\S{4}-\S{4}$", reset["temporaryPassword"]))
        self.assertEqual(self.as_(cookie, "GET", "/api/properties").status, 401)

    def test_a_manager_sees_only_their_team(self):
        sbu_id, _, every = self.sample()
        other_sbu = next(p["sbu_id"] for p in every if p["sbu_id"] != sbu_id)
        teammate, _ = self.person("PROPERTY_OFFICER", types=[sbu_id])
        stranger, _ = self.person("PROPERTY_OFFICER", types=[other_sbu])
        me, cookie = self.person("PROPERTY_MANAGER", types=[sbu_id])
        users = self.as_(cookie, "GET", "/api/users").json()["users"]
        seen = {u["id"] for u in users}
        self.assertTrue({teammate, me} <= seen)
        self.assertNotIn(stranger, seen)
        self.assertTrue(all(sbu_id in u["scope"]["types"] for u in users))


class RoleTests(AccessTestCase):

    def test_a_role_change_applies_at_once(self):
        _, cookie = self.person("VIEWER")
        self.assertEqual(self.as_(cookie, "GET", "/api/export/properties.csv").status, 403)
        self.ok("PUT", "/api/roles/VIEWER", data={"permissions": {"properties.export": "yes"}})
        self.assertEqual(self.as_(cookie, "GET", "/api/export/properties.csv").status, 200)

    def test_role_rules(self):
        self.assertEqual(self.request("PUT", "/api/roles/SUPER_ADMIN",
                                      data={"permissions": {"users.view": "no"}}).status, 400)
        self.assertEqual(self.request("PUT", "/api/roles/VIEWER",
                                      data={"permissions": {"types.delete": "limited"}}).status, 400)
        made = self.ok("POST", "/api/roles", 201, data={"name": "Site Inspector", "copyFrom": "VIEWER"})
        self.assertEqual(made["code"], "SITE_INSPECTOR")
        self.assertEqual(made["permissions"]["dashboard.view"], "yes")
        self.assertEqual(self.request("DELETE", "/api/roles/VIEWER").status, 400)
        self.ok("DELETE", "/api/roles/SITE_INSPECTOR")


class AuditTests(AccessTestCase):

    def test_changes_and_sign_ins_are_logged(self):
        user_id, cookie = self.person("AUDITOR")
        self.ok("DELETE", "/api/properties/1")
        log = self.as_(cookie, "GET", "/api/audit").json()["entries"]
        actions = [e["action"] for e in log]
        self.assertIn("property.delete", actions)
        self.assertIn("auth.sign_in", actions)
        deleted = next(e for e in log if e["action"] == "property.delete")
        self.assertEqual(deleted["userEmail"], TEST_EMAIL)
        self.assertIn("document", deleted["detail"])
        only_auth = self.as_(cookie, "GET", "/api/audit", query={"category": "auth"}).json()["entries"]
        self.assertTrue(only_auth and all(e["action"].startswith("auth.") for e in only_auth))
        _, viewer = self.person("VIEWER")
        self.assertEqual(self.as_(viewer, "GET", "/api/audit").status, 403)
