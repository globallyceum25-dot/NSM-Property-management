"""Signing in: accounts, sessions, lockout, and what needs a session."""

import uuid

from server import auth, db

from .support import RegisterTestCase


class SignInTests(RegisterTestCase):

    def make_user(self, role="VIEWER", password="a long enough password"):
        email = "user-%s@example.lk" % uuid.uuid4().hex[:8]
        conn = db.get_conn()
        auth.create_user(conn, email, "Test User", role, password)
        db.release()
        return email, password

    def sign_in(self, email, password, remember=False):
        return self.request("POST", "/api/auth/login", anonymous=True,
                            data={"email": email, "password": password, "remember": remember})

    def test_passwords_are_hashed_and_checked(self):
        stored = auth.hash_password("a long enough password")
        self.assertTrue(stored.startswith("pbkdf2_sha256$"))
        self.assertNotIn("a long enough password", stored)
        self.assertTrue(auth.verify_password("a long enough password", stored))
        self.assertFalse(auth.verify_password("a long enough passwore", stored))
        self.assertFalse(auth.verify_password("x", "garbage"))
        self.assertIsNotNone(auth.password_problem("short"))
        self.assertIsNotNone(auth.password_problem("aaaaaaaaaaaa"))
        self.assertIsNone(auth.password_problem("a long enough password"))

    def test_the_register_needs_a_session(self):
        for path in ("/api/properties", "/api/stats", "/api/documents", "/api/sbus",
                     "/api/import/template.xlsx", "/api/export/properties.csv"):
            response = self.request("GET", path, anonymous=True)
            self.assertEqual(response.status, 401, path)
            self.assertTrue(response.json()["signIn"])
        self.assertEqual(self.request("POST", "/api/sbus", anonymous=True, data={}).status, 401)
        # Public: the health check, and the sign-in endpoints themselves.
        self.assertEqual(self.request("GET", "/api/reference", anonymous=True).status, 200)
        status = self.ok("GET", "/api/auth/status", anonymous=True)
        self.assertEqual((status["signedIn"], status["needsSetup"]), (False, False))
        # The pages load for anyone; they ask for a session themselves.
        self.assertEqual(self.request("GET", "/login", anonymous=True).status, 200)
        self.assertIn(b"Welcome back", self.request("GET", "/login", anonymous=True).body)

    def test_sign_in_use_and_sign_out(self):
        email, password = self.make_user("PROPERTY_MANAGER")
        response = self.sign_in(email.upper(), password)          # email is not case-sensitive
        self.assertEqual(response.status, 200)
        self.assertEqual(response.json()["user"]["roleLabel"], "Property Manager")
        cookie_header = response.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie_header)
        self.assertIn("SameSite=Lax", cookie_header)
        self.assertNotIn("Max-Age", cookie_header)                  # a browser-session cookie
        cookie = cookie_header.split(";")[0]

        status = self.ok("GET", "/api/auth/status", headers={"Cookie": cookie})
        self.assertEqual(status["user"]["email"], email)
        self.assertEqual(self.request("GET", "/api/properties", headers={"Cookie": cookie}).status, 200)

        self.ok("POST", "/api/auth/logout", headers={"Cookie": cookie})
        self.assertEqual(self.request("GET", "/api/properties", headers={"Cookie": cookie}).status, 401)

    def test_keep_me_signed_in_lasts_30_days(self):
        email, password = self.make_user()
        cookie_header = self.sign_in(email, password, remember=True).headers["Set-Cookie"]
        self.assertIn("Max-Age=%d" % (30 * 86400), cookie_header)

    def test_wrong_details_say_nothing_about_which_was_wrong(self):
        email, password = self.make_user()
        wrong_password = self.sign_in(email, "not the password")
        unknown_email = self.sign_in("nobody-%s@example.lk" % uuid.uuid4().hex[:6], password)
        self.assertEqual(wrong_password.status, 401)
        self.assertEqual(unknown_email.status, 401)
        self.assertEqual(wrong_password.json()["error"], unknown_email.json()["error"])

    def test_five_wrong_passwords_lock_the_account(self):
        email, password = self.make_user()
        for _ in range(auth.MAX_FAILED):
            self.assertEqual(self.sign_in(email, "wrong password!").status, 401)
        locked = self.sign_in(email, password)          # even the right one, for now
        self.assertEqual(locked.status, 423)
        self.assertIn("locked", locked.json()["error"])

    def test_switched_off_accounts_and_new_passwords(self):
        email, password = self.make_user()
        cookie = self.sign_in(email, password).headers["Set-Cookie"].split(";")[0]
        conn = db.get_conn()
        auth.set_password(conn, email, "a brand new password")      # signs out everywhere
        db.release()
        self.assertEqual(self.request("GET", "/api/properties", headers={"Cookie": cookie}).status, 401)
        self.assertEqual(self.sign_in(email, password).status, 401)
        self.assertEqual(self.sign_in(email, "a brand new password").status, 200)
        conn = db.get_conn()
        conn.execute("UPDATE app_user SET is_active = 0 WHERE email = ?", (email,))
        conn.commit()
        db.release()
        self.assertEqual(self.sign_in(email, "a brand new password").status, 403)

    def test_changes_from_another_site_are_refused(self):
        response = self.request("POST", "/api/sbus", data={"code": "X", "name": "X"},
                                headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status, 403)
        same = self.request("POST", "/api/sbus", data={"code": "SAMEORIGIN", "name": "Same origin"},
                            headers={"Origin": self.base})
        self.assertEqual(same.status, 201)

    def test_setup_is_only_for_a_register_with_no_accounts(self):
        response = self.request("POST", "/api/auth/setup", anonymous=True,
                                data={"name": "X", "email": "x@example.lk", "password": "a long enough password",
                                      "confirm": "a long enough password", "setupCode": "AAAA-BBBB"})
        self.assertEqual(response.status, 409)

    def test_setup_code_and_first_admin(self):
        conn = db.get_conn()
        users = conn.execute("SELECT * FROM app_user").fetchall()
        sessions = conn.execute("SELECT * FROM app_session").fetchall()
        conn.execute("DELETE FROM app_session")
        conn.execute("DELETE FROM app_user")
        conn.commit()
        try:
            code = auth.setup_code(conn)
            self.assertRegex(code, r"^[0-9A-F]{4}-[0-9A-F]{4}$")
            body = {"name": "First Admin", "email": "first@example.lk", "password": "a long enough password",
                    "confirm": "a long enough password"}
            self.assertTrue(self.ok("GET", "/api/auth/status", anonymous=True)["needsSetup"])
            wrong = self.request("POST", "/api/auth/setup", anonymous=True, data=dict(body, setupCode="0000-0000"))
            self.assertEqual(wrong.status, 400)
            right = self.request("POST", "/api/auth/setup", anonymous=True, data=dict(body, setupCode=code.lower()))
            self.assertEqual(right.status, 201)
            self.assertEqual(right.json()["user"]["role"], "SUPER_ADMIN")
            self.assertIsNone(auth.setup_code(conn))
        finally:
            conn.execute("DELETE FROM app_session")
            conn.execute("DELETE FROM app_user")
            for u in users:
                conn.execute("INSERT INTO app_user (%s) VALUES (%s)" % (", ".join(u.keys()), ", ".join("?" * len(u))),
                             tuple(u[k] for k in u.keys()))
            for s in sessions:
                conn.execute("INSERT INTO app_session (%s) VALUES (%s)" % (", ".join(s.keys()), ", ".join("?" * len(s))),
                             tuple(s[k] for k in s.keys()))
            conn.commit()
            db.release()
