"""The front end in a real browser: every view renders the sample register
without a JavaScript error.

Needs Playwright (requirements-dev.txt, then `python -m playwright install
chromium`); skipped without it, unless REQUIRE_BROWSER_TESTS=1 (as in CI),
when a missing browser is a failure rather than a silent skip.
"""

import os
import unittest

from .support import RegisterTestCase

try:
    from playwright.sync_api import expect, sync_playwright
    HAVE_PLAYWRIGHT = True
except ImportError:
    HAVE_PLAYWRIGHT = False

REQUIRED = os.environ.get("REQUIRE_BROWSER_TESTS") == "1"


@unittest.skipIf(not HAVE_PLAYWRIGHT and not REQUIRED, "Playwright is not installed")
class BrowserSmokeTest(RegisterTestCase):

    def test_every_view_renders_without_errors(self):
        if not HAVE_PLAYWRIGHT:
            self.fail("REQUIRE_BROWSER_TESTS=1 but Playwright is not installed")
        errors = []
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(self.base + "/")
            page.get_by_text("13 properties in the register").wait_for()

            # Page switches cross-fade, so each check waits for what the page
            # shows once it has arrived and loaded, not for a passing state.
            page.goto(self.base + "/#documents")
            page.get_by_text("9 documents across 7 properties").wait_for()
            for view, heading in (("sbus", "Property types"), ("entities", "Owning companies")):
                page.goto(self.base + "/#" + view)
                page.locator("#view-%s.is-active h1" % view).get_by_text(heading).wait_for()
            # Master sheets opens on its first sheet, whose name replaces the
            # page's "Master sheets" heading as soon as it loads.
            page.goto(self.base + "/#masters")
            page.locator("#view-masters.is-active #master-title").get_by_text("Locations").wait_for()
            expect(page.locator("#master-rows tr")).to_have_count(13)
            page.goto(self.base + "/#dashboard")
            page.locator("#view-dashboard.is-active").wait_for()

            # Open a property from the register: the drawer loads its documents.
            page.goto(self.base + "/#property/1")
            drawer = page.locator("#drawer")
            drawer.get_by_text("Corporate Head Office").first.wait_for()
            drawer.get_by_text("Deed of Transfer No. 4821").first.wait_for()
            browser.close()
        self.assertEqual(errors, [])
