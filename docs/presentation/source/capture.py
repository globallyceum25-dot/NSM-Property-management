"""Capture the demo walkthroughs for the presentation.

Runs a throwaway copy of the register (the live database copied, plus sample
documents and demo accounts), walks through each module in headless Chrome,
and saves a screenshot per step with the exact position of the control each
step points at. build.py turns the result into the presentation.

    python capture.py OUT_DIR            (needs: pip install playwright pillow openpyxl;
                                          uses the Google Chrome already installed)
"""

import datetime
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

from openpyxl import Workbook
from playwright.sync_api import sync_playwright

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PORT = 8017
BASE = "http://127.0.0.1:%d" % PORT
W, H = 1440, 810


# --- a demo copy of the register ------------------------------------------------

def make_copy(data_dir):
    os.makedirs(data_dir, exist_ok=True)
    src = sqlite3.connect("file:%s?mode=ro" % os.path.join(REPO, "data", "properties.db"), uri=True)
    dst = sqlite3.connect(os.path.join(data_dir, "properties.db"))
    src.backup(dst)
    dst.close()
    src.close()


def start_server(data_dir, admin_password):
    env = dict(os.environ, REGISTER_DATA_DIR=data_dir, DATABASE_URL="",
               REGISTER_ADMIN_EMAIL="demo.admin@example.test", REGISTER_ADMIN_PASSWORD=admin_password)
    proc = subprocess.Popen([sys.executable, "-m", "server.app", "--port", str(PORT)], cwd=REPO, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            urllib.request.urlopen(BASE + "/api/reference", timeout=1)
            return proc
        except OSError:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit("The demo register did not start.")


def make_admin(data_dir, password):
    """The demo copy already has accounts, so the start-up bootstrap does not
    run: add the demo Super Admin directly."""
    os.environ.update(REGISTER_DATA_DIR=data_dir, DATABASE_URL="", REGISTER_PBKDF2_ITERATIONS="20000")
    sys.path.insert(0, REPO)
    from server import auth, db
    db.init_db()
    conn = db.get_conn()
    if not conn.execute("SELECT 1 FROM app_user WHERE email = 'demo.admin@example.test'").fetchone():
        auth.create_user(conn, "demo.admin@example.test", "Demo Administrator", "SUPER_ADMIN", password)
    db.release()


def tiny_pdf(title, lines):
    """A one-page PDF with a heading and a few lines, for the sample documents."""
    def esc(text):
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    body = ["BT /F2 22 Tf 64 760 Td (%s) Tj ET" % esc(title),
            "0.75 0.8 0.8 RG 64 742 m 531 742 l S"]
    y = 712
    for line in lines:
        body.append("BT /F1 13 Tf 64 %d Td (%s) Tj ET" % (y, esc(line)))
        y -= 24
    body.append("BT /F1 10 Tf 64 60 Td (Sample document - demo copy of the Property Register) Tj ET")
    stream = "\n".join(body).replace("\u2014", "-").encode("latin-1", "replace")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def seed(request):
    """Sample documents across the renewal ladder, and demo accounts."""
    today = datetime.date.today()
    props = request.get(BASE + "/api/properties").json()
    by_type = {}
    for p in props:
        by_type.setdefault(p["sbu_name"], []).append(p)
    pick = by_type["Educational"][:4] + by_type["Commercial Properties"][:3] + by_type["Bus Yards"][:2] \
        + by_type["Hostels"][:2]

    def day(months):
        return (today + datetime.timedelta(days=int(months * 30.4))).isoformat()

    samples = [
        ("DEED", "Deed of Transfer No. 4821", None, "Notary Public, Colombo", 0),
        ("LEASE_AGREEMENT", "Lease agreement — school premises", day(2), "Landowner", 1),
        ("SURVEY_PLAN", "Survey plan No. 1907", None, "Licensed Surveyor", 2),
        ("INSURANCE_POLICY", "Fire & allied perils policy", day(-1), "Insurer", 3),
        ("LEASE_AGREEMENT", "Rent agreement — showroom", day(5), "Landlord", 4),
        ("TAX_RECEIPT", "Assessment rates 2026", day(8), "Municipal Council", 5),
        ("DEED", "Deed of Transfer No. 1260", None, "Notary Public, Kalutara", 6),
        ("PERMIT_APPROVAL", "Certificate of conformity", day(11), "Pradeshiya Sabha", 7),
        ("LEASE_AGREEMENT", "Bus yard lease", day(16), "Landowner", 8),
        ("VALUATION_REPORT", "Valuation report 2026", None, "Chartered Valuer", 9),
        ("LEASE_AGREEMENT", "Hostel lease agreement", day(3.5), "Landowner", 10),
    ]
    for doc_type, title, expiry, counterparty, i in samples:
        p = pick[i % len(pick)]
        form = {"doc_type": doc_type, "title": title, "reference_no": "REF-%04d" % (1200 + i),
                "issue_date": (today - datetime.timedelta(days=400 + 37 * i)).isoformat(),
                "counterparty": counterparty}
        if expiry:
            form["expiry_date"] = expiry
        files = {"file": {"name": title.split(" —")[0].replace(" ", "-") + ".pdf", "mimeType": "application/pdf",
                          "buffer": tiny_pdf(title, [p["name"][:70], "Reference: REF-%04d" % (1200 + i),
                                                     "Party: " + counterparty])}}
        r = request.post(BASE + "/api/properties/%d/documents" % p["id"], multipart=dict(form, **files))
        assert r.status == 201, r.text()

    sbus = {s["name"]: s["id"] for s in request.get(BASE + "/api/sbus").json()}
    people = [
        ("Demo Manager", "demo.manager@example.test", "PROPERTY_MANAGER", ["Educational", "Hostels"]),
        ("Demo Officer", "demo.officer@example.test", "PROPERTY_OFFICER", ["Bus Yards"]),
        ("Demo Document Controller", "demo.documents@example.test", "DOCUMENT_CONTROLLER", []),
        ("Demo Auditor", "demo.auditor@example.test", "AUDITOR", []),
        ("Demo Viewer", "demo.viewer@example.test", "VIEWER", []),
    ]
    made = {}
    for name, email, role, types in people:
        r = request.post(BASE + "/api/users", data={"name": name, "email": email, "role": role,
                                                     "scope": {"types": [sbus[t] for t in types], "companies": []}},
                         headers={"Origin": BASE})
        assert r.status == 201, r.text()
        made[email] = r.json()
    return made


def bulk_file(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Properties"
    ws.append(["Property name", "Property type", "Owning company", "Tenure", "City / town", "District",
               "Latitude", "Longitude", "Land extent", "Land unit"])
    ws.append(["Lyceum Campus - Galle Annex", "Educational", "LIS", "Freehold", "Galle", "Galle",
               6.0535, 80.2210, 48, "Perches"])
    ws.append(["Kandy City Showroom", "Commercial Properties", "NCGE", "Rented in", "Kandy", "Kandy",
               7.2936, 80.6351, 22.5, "Perches"])
    ws.append(["Matara Bus Yard", "Bus Yards", "", "Leasehold", "Matara", "Matara", 5.9549, 80.5550, 1.5, "Acres"])
    ws.append(["Negombo Staff Hostel", "Hostels", "LIS", "Rented in", "Negombo", "Gampaha", "", "", 30, "Perches"])
    ws.append(["Jaffna Warehouse", "Warehouse", "CNT", "Owned outright", "Jaffna", "Jaffna", 9.6615, 80.0255, 1,
               "Acres"])
    wb.save(path)


# --- walking through the screens --------------------------------------------------

class Recorder(object):
    def __init__(self, page, out):
        self.page, self.out, self.modules, self.current = page, out, [], None

    def module(self, key, url_label):
        self.current = {"key": key, "url": url_label, "steps": []}
        self.modules.append(self.current)

    def _box(self, selector, pad=6):
        el = self.page.locator(selector).first
        el.wait_for(state="visible", timeout=8000)
        b = el.bounding_box()
        x, y = max(0, b["x"] - pad), max(0, b["y"] - pad)
        w, h = min(W - x, b["width"] + 2 * pad), min(H - y, b["height"] + 2 * pad)
        return [round(x / W * 100, 2), round(y / H * 100, 2), round(w / W * 100, 2), round(h / H * 100, 2)]

    def shot(self, hot, label, pos="below", cursor=None, click=True, hold=3.2, settle=700):
        """One step: the screen as it is now, a highlight on `hot`, and the
        cursor travelling to `cursor` (default: the middle of `hot`)."""
        page = self.page
        page.wait_for_timeout(settle)
        n = sum(len(m["steps"]) for m in self.modules)
        name = "%s-%02d.png" % (self.current["key"], len(self.current["steps"]) + 1)
        box = self._box(hot) if hot else None
        target = self._box(cursor, 0) if cursor else box
        point = [round(target[0] + target[2] / 2, 2), round(target[1] + target[3] / 2, 2)] if target else [50, 50]
        page.screenshot(path=os.path.join(self.out, name))
        self.current["steps"].append({"img": name, "hot": box, "label": label, "pos": pos, "cur": point,
                                      "click": click, "hold": hold})
        print("  %3d %s  %s" % (n + 1, name, label))


def walk(page, rec, admin_password, demo_users):
    def go(hash_, wait="#property-cards"):
        page.goto(BASE + "/" + hash_)
        page.wait_for_load_state("networkidle")
        if wait:
            page.locator(wait).first.wait_for(timeout=10000)

    def close_all():
        page.keyboard.press("Escape")
        page.evaluate("""() => { document.querySelectorAll('.modal, .drawer, .popover').forEach(e => e.hidden = true);
                                  const s = document.getElementById('scrim'); if (s) s.hidden = true; }""")

    # 01 Sign-in & security
    rec.module("signin", "127.0.0.1 › Sign in")
    page.goto(BASE + "/login")
    page.wait_for_load_state("networkidle")
    page.fill("#email", "demo.admin@example.test")
    rec.shot("#email", "Company email — accounts are given, not self-registered", cursor="#password")
    page.fill("#password", "not the right one")
    rec.shot("#password", "Password (hidden, Caps Lock warning)", cursor="#btn-signin")
    page.click("#btn-signin")
    page.locator("#login-alert").wait_for()
    rec.shot("#login-alert", "One generic error · 5 tries, then a 15-minute lock", cursor="#password", click=False)
    page.fill("#password", admin_password)
    rec.shot("label:has(input[name=remember])", "Keep me signed in for 30 days", "below", cursor="#btn-signin")
    page.click("#btn-signin")
    page.locator("#property-cards .pcard").first.wait_for(timeout=15000)
    page.wait_for_load_state("networkidle")
    page.click("#btn-account")
    rec.shot("#account-pop", "Signed in: name, role, My access, sign out", "left", cursor="#btn-my-access", hold=3.6)
    close_all()

    # 02 Portfolio
    rec.module("portfolio", "Property Register › Portfolio")
    go("#portfolio")
    page.wait_for_timeout(1200)
    rec.shot("#map-panel", "Every property on the map, coloured by type", "below right", cursor="#kpi-strip")
    rec.shot("#kpi-strip", "Live totals — each card opens its list", cursor="#tenure-tabs button:nth-child(2)")
    page.click("#tenure-tabs button:nth-child(2)")
    page.wait_for_timeout(900)
    rec.shot("#tenure-tabs", "Freehold · Leasehold · Rented in · Leased out", cursor="#mode-toggle [data-mode=grid]")
    page.click("#mode-toggle [data-mode=grid]")
    page.wait_for_timeout(900)
    rec.shot("#mode-toggle", "Map · Grid · Table views", "below right", cursor="#mode-toggle [data-mode=table]")
    page.click("#mode-toggle [data-mode=table]")
    page.wait_for_timeout(900)
    rec.shot("#table-panel", "The full register as a sortable table", "below", cursor="#search")
    page.click("#tenure-tabs button:nth-child(1)")
    page.fill("#search", "Lyceum")
    page.wait_for_timeout(1000)
    rec.shot("#search", "Search by code, name, city or district", click=False, hold=3.6)
    page.fill("#search", "")

    # 03 Property record
    rec.module("property", "Property Register › Property")
    pid = page.evaluate("async () => (await (await fetch('/api/properties')).json())"
                        ".find(p => p.sbu_name === 'Educational' && p.document_count > 0).id")
    go("#property/%d" % pid, "#drawer .detail-actions")
    page.wait_for_timeout(1500)
    rec.shot("#drawer", "One record: type, owner, location, areas, documents", "left", cursor="#drawer [data-edit]")
    page.click("#drawer [data-edit]")
    page.locator("#property-modal").wait_for()
    page.wait_for_timeout(900)
    rec.shot("#property-modal .modal-card", "Required fields marked; picked from master lists", "left",
             cursor="#picker-map")
    page.locator("#picker-map").scroll_into_view_if_needed()
    page.wait_for_timeout(1200)
    rec.shot("#picker-map", "Drop the pin on the map — or paste coordinates", "below", cursor="#pf-extent-unit")
    page.locator("#pf-extent-unit").scroll_into_view_if_needed()
    page.fill("#property-form input[name=extent_value]", "40")
    page.locator("#property-form input[name=extent_value]").dispatch_event("input")
    page.wait_for_timeout(600)
    rec.shot("#extent-sqft", "Perches, acres, hectares… shown in sq ft", "below", cursor="#btn-save-property",
             click=False, hold=3.6)
    close_all()

    # 04 Bulk upload
    rec.module("bulk", "Property Register › Bulk upload")
    go("#portfolio")
    page.click("#btn-new-property")
    page.locator("#property-modal").wait_for()
    rec.shot("[data-pmode=bulk]", "One property — or many at once", cursor="[data-pmode=bulk]")
    page.click("[data-pmode=bulk]")
    page.wait_for_timeout(800)
    rec.shot("#btn-bulk-template", "Excel template with drop-downs from the live register", cursor="#bulk-dropzone")
    path = os.path.join(tempfile.mkdtemp(), "new-properties.xlsx")
    bulk_file(path)
    page.set_input_files("#bulk-file", path)
    page.locator("#bulk-result table, #bulk-result .bulk-table").first.wait_for(timeout=15000)
    page.wait_for_timeout(900)
    rec.shot("#bulk-result", "Every row checked before anything is saved", "left", cursor="#btn-bulk-import",
             hold=3.8)
    rec.shot("#btn-bulk-import", "Import the rows that pass — in one go", "left", click=False, hold=3.2)
    close_all()

    # 05 Documents
    rec.module("documents", "Property Register › Documents")
    go("#documents", "#doc-rows tr")
    page.wait_for_timeout(900)
    rec.shot("#doc-tabs", "All · With file · No file · Expiring · Expired", cursor="#doc-tabs [data-doc-status=expiring]")
    page.click("#doc-tabs [data-doc-status=expiring]")
    page.wait_for_timeout(900)
    rec.shot("#doc-rows", "Expiring documents, soonest first", "below", cursor="#doc-rows tr")
    page.click("#doc-rows tr")
    page.locator("#doc-drawer .dd-preview").wait_for()
    page.wait_for_timeout(1800)
    rec.shot("#doc-drawer .dd-preview", "Scan previewed in place — view or download", "left",
             cursor="#btn-close-doc")
    close_all()
    go("#documents", "#doc-rows tr")
    page.click("#btn-new-doc")
    page.locator("#doc-modal").wait_for()
    page.wait_for_timeout(700)
    rec.shot("#doc-modal .modal-card", "Attach: type, dates, counterparty, the file", "left",
             cursor="#doc-dropzone", click=False, hold=3.6)
    close_all()

    # 06 Dashboard & alerts
    rec.module("dashboard", "Property Register › Dashboard")
    go("#dashboard", "#view-dashboard.is-active")
    page.wait_for_timeout(2200)
    rec.shot("#dashboard .dash-hero", "Signals: what needs attention now", "below",
             cursor="#dashboard [data-xf-dim] >> visible=true")
    target = page.locator("#dashboard [data-xf-dim] >> visible=true").first
    target.scroll_into_view_if_needed()
    page.wait_for_timeout(900)
    rec.shot("#dashboard [data-xf-dim] >> visible=true", "Click any slice or bar to filter everything", "right",
             cursor="#dashboard [data-xf-dim] >> visible=true")
    target.dispatch_event("click")      # chart marks animate, so they never count as "stable"
    page.wait_for_timeout(1500)
    page.evaluate("document.getElementById('view-dashboard').scrollTop = 0")
    page.wait_for_timeout(700)
    rec.shot("#dashboard .xf-active", "Every figure now follows that filter", "below", cursor="#btn-alerts", hold=3.4)
    page.click("#btn-alerts")
    page.locator("#alerts-pop").wait_for()
    page.wait_for_timeout(700)
    rec.shot("#alerts-pop", "The bell: documents expiring soon", "left", click=False, hold=3.6)
    close_all()

    # 07 Property types & companies
    rec.module("groups", "Property Register › Property types")
    go("#sbus", "#sbu-cards .tile, #sbu-cards > *")
    page.wait_for_timeout(1000)
    rec.shot("#sbu-cards", "Property types with live counts", "below", cursor="#sbu-cards > *:first-child")
    page.locator("#sbu-cards > *:first-child").click()
    page.wait_for_timeout(1600)
    rec.shot("#sbu-detail", "A type's own page: its properties and documents", "below", cursor="[data-view=entities]")
    go("#entities", "#entity-cards > *")
    page.wait_for_timeout(900)
    rec.shot("#entity-cards", "Owning companies that hold title", "below", cursor="#entity-cards > *:first-child",
             click=False, hold=3.4)

    # 08 Master sheets
    rec.module("masters", "Property Register › Master sheets")
    go("#masters", "#view-masters.is-active #masters-nav .master-link")
    page.wait_for_timeout(900)
    rec.shot("#masters-nav", "Editable masters and locked system lists", "right",
             cursor="#masters-nav .master-link:nth-of-type(3)")
    page.locator("#masters-nav .master-link", has_text="Property types").click()
    page.wait_for_timeout(900)
    rec.shot("#master-grid", "One place to maintain every list", "below", cursor="#masters-nav .master-link >> text=Districts")
    page.locator("#masters-nav .master-link", has_text="Districts").click()
    page.wait_for_timeout(900)
    rec.shot("#master-grid", "System lists: 25 districts, 9 provinces, units…", "below", click=False, hold=3.4)

    # 09 Users
    rec.module("users", "Property Register › Users & access")
    go("#access", "#people-rows tr")
    page.wait_for_timeout(900)
    rec.shot("#people-rows", "Everyone who can sign in — role, scope, status", "below", cursor="#btn-add-person")
    page.click("#btn-add-person")
    page.locator("#person-modal").wait_for()
    page.fill("#person-form input[name=name]", "Demo Site Officer")
    page.fill("#person-form input[name=email]", "demo.site@example.test")
    page.select_option("#person-form select[name=role]", "PROPERTY_OFFICER")
    page.wait_for_timeout(400)
    page.locator("#person-scope-pick [data-scope=types]", has_text="Educational").click()
    page.wait_for_timeout(500)
    rec.shot("#person-scope-pick", "Role + data scope: which types and companies", "left", cursor="#btn-save-person")
    page.click("#btn-save-person")
    page.locator("#temp-code").wait_for()
    page.wait_for_timeout(600)
    rec.shot(".temp-box", "A one-time password, changed at first sign-in", "below",
             cursor="#person-created [data-close-modal]")
    page.click("#person-created [data-close-modal]")
    page.wait_for_timeout(600)
    page.locator("#people-rows tr", has_text="Demo Officer").click()
    page.locator("#person-drawer").wait_for()
    page.wait_for_timeout(700)
    page.evaluate("document.getElementById('person-body').scrollTop = 99999")
    page.wait_for_timeout(400)
    rec.shot("#person-body .detail-section", "Reset password · sign out everywhere · switch off", "left",
             click=False, hold=3.6)
    close_all()

    # 10 Roles, permissions & activity
    rec.module("roles", "Property Register › Roles & permissions")
    go("#access", "#people-rows tr")
    page.click("[data-atab=roles]")
    page.locator("#role-editor .perm-row").first.wait_for()
    page.locator("#roles-nav [data-role]", has_text="Property Officer").click()
    page.wait_for_timeout(800)
    rec.shot("#role-editor .perm-module", "Yes · Limited · No for every action", "below", cursor="#roles-nav [data-compare]")
    page.click("#roles-nav [data-compare]")
    page.wait_for_timeout(800)
    rec.shot("#role-editor .cmp-table", "The whole matrix, side by side", "below", cursor="[data-atab=activity]")
    page.click("[data-atab=activity]")
    page.locator("#audit-list .audit-item").first.wait_for()
    page.wait_for_timeout(800)
    rec.shot("#audit-list", "Activity: who changed what, and when", "below", cursor="#btn-account")
    # What a Property Officer sees of their own access.
    officer = demo_users["demo.officer@example.test"]
    page.evaluate("fetch('/api/auth/logout', {method: 'POST'})")
    page.goto(BASE + "/login")
    page.fill("#email", "demo.officer@example.test")
    page.fill("#password", officer["temporaryPassword"])
    page.click("#btn-signin")
    page.locator("#change-view").wait_for()
    new_pw = "officer demo " + secrets.token_hex(4)
    page.fill("#c-password", new_pw)
    page.fill("#c-confirm", new_pw)
    page.click("#btn-change")
    page.locator("#property-cards .pcard").first.wait_for(timeout=15000)
    page.wait_for_timeout(900)
    page.click("#btn-account")
    page.click("#btn-my-access")
    page.locator("#my-access-body .my-module").first.wait_for()
    page.wait_for_timeout(700)
    rec.shot("#my-access-body .my-scope", "Everyone sees the access they were given", "below", click=False, hold=4)


def main():
    out = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "frames")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    data_dir = tempfile.mkdtemp(prefix="register-demo-")
    admin_password = "demo admin " + secrets.token_hex(6)
    make_copy(data_dir)
    make_admin(data_dir, admin_password)
    server = start_server(data_dir, admin_password)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            context = browser.new_context(viewport={"width": W, "height": H}, reduced_motion="reduce",
                                          color_scheme="light")
            page = context.new_page()
            login = context.request.post(BASE + "/api/auth/login", data={
                "email": "demo.admin@example.test", "password": admin_password})
            assert login.status == 200, login.text()
            demo_users = seed(context.request)
            context.request.post(BASE + "/api/auth/logout")
            rec = Recorder(page, out)
            walk(page, rec, admin_password, demo_users)
            browser.close()
        with open(os.path.join(out, "manifest.json"), "w") as fh:
            json.dump({"size": [W, H], "modules": rec.modules}, fh, indent=1)
        print("Captured %d steps in %d modules." % (sum(len(m["steps"]) for m in rec.modules), len(rec.modules)))
    finally:
        server.terminate()
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
