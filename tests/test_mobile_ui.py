"""Optional actual-browser smoke test: MTOS_BROWSER_TESTS=1 pytest tests/test_mobile_ui.py."""

import os
import threading

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("MTOS_BROWSER_TESTS") != "1", reason="optional browser smoke test"
)


def test_iphone_add_edit_search_and_retire(tmp_path):
    from playwright.sync_api import expect, sync_playwright
    from werkzeug.serving import make_server

    from mtos.app import create_app

    app = create_app({"DATA_ROOT": tmp_path / "data", "TESTING": True})
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            expect(page.locator("#summary")).to_contain_text("0 assets")
            page.locator("#add").click()
            expect(page.locator("[name=id]").first).to_have_value("L001")
            page.locator("[name=reporting_mark]").fill("SAL")
            page.locator("[name=road_number]").fill("4202")
            page.locator("[name=possession]").select_option("received")
            page.locator("#asset-form button[type=submit]").click()
            expect(page.locator("#save-status")).to_have_text("Saved")
            page.locator("[name=notes]").fill("Test cab unit")
            page.locator("#asset-form button[type=submit]").click()
            expect(page.locator("#save-status")).to_have_text("Saved")
            page.locator("#back").click()
            page.locator("#search").fill("SAL4202")
            expect(page.locator(".card")).to_have_count(1)
            page.locator(".card").click()
            expect(page.locator("[name=notes]")).to_have_value("Test cab unit")
            assert not page.evaluate(
                "document.documentElement.scrollWidth > window.innerWidth"
            )
            page.locator("[name=status]").select_option("retired")
            page.locator("#asset-form button[type=submit]").click()
            expect(page.locator("#save-status")).to_have_text("Saved")
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
