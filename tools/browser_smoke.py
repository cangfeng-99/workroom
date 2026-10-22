"""Browser smoke test: installed Chrome/Edge channel only, no browser download.

Not a product test. Proves the local Playwright + installed-browser path works.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOT = ROOT / "tasks" / "reports" / "browser-smoke.png"
HTML = """<!doctype html><html><head><meta charset="utf-8"><title>smoke</title></head>
<body><button id="b">idle</button>
<script>
document.getElementById('b').addEventListener('click', function () {
  this.textContent = 'clicked';
  this.setAttribute('data-state', 'changed');
});
</script></body></html>"""


def run() -> dict:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    result = {"status": "FAIL", "channel": None, "steps": []}
    SHOT.parent.mkdir(parents=True, exist_ok=True)
    last_err = []
    try:
        with sync_playwright() as p:
            for channel in ("chrome", "msedge"):
                try:
                    browser = p.chromium.launch(channel=channel, headless=True)
                except PlaywrightError as exc:
                    last_err.append(f"{channel}: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}")
                    continue
                result["channel"] = channel
                try:
                    page = browser.new_page()
                    page.set_content(HTML, wait_until="load")
                    result["steps"].append("set_content:ok")

                    btn = page.locator("#b")
                    if btn.inner_text() != "idle":
                        raise AssertionError("initial text is not 'idle'")
                    result["steps"].append("initial_dom:ok")

                    btn.click()
                    btn.wait_for(state="visible")
                    txt = btn.inner_text()
                    state = btn.get_attribute("data-state")
                    if txt != "clicked":
                        raise AssertionError(f"after click text={txt!r}, expected 'clicked'")
                    if state != "changed":
                        raise AssertionError(f"after click data-state={state!r}, expected 'changed'")
                    result["steps"].append("click_state_change:ok")

                    page.screenshot(path=str(SHOT), full_page=True)
                    if not SHOT.is_file() or SHOT.stat().st_size < 1000:
                        raise AssertionError("screenshot missing or too small")
                    result["screenshot"] = str(SHOT)
                    result["steps"].append("screenshot:ok")
                    result["status"] = "PASS"
                finally:
                    browser.close()
                break
    except (PlaywrightError, AssertionError, OSError) as exc:
        last_err.append(f"{type(exc).__name__}: {str(exc).splitlines()[0][:300]}")
        result["status"] = "FAIL"

    result["error"] = last_err
    result["is_product_test"] = False
    return result


if __name__ == "__main__":
    data = run()
    print(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(0 if data["status"] == "PASS" else 1)
