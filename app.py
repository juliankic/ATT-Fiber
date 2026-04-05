import os
import asyncio
from flask import Flask, request, jsonify
from playwright.async_api import async_playwright
import requests

app = Flask(__name__)

GHL_API_KEY = os.environ.get("GHL_API_KEY", "pit-08166086-17f2-4dcc-88d2-8f065adae15c")
GHL_LOCATION_ID = os.environ.get("GHL_LOCATION_ID", "6VJ6jJ4IxhkiJLzHZUcx")
TAG_FIBER = "fiber-eligible"
TAG_NO_FIBER = "no-coverage"


async def check_att_fiber(address: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            await page.goto("https://www.att.com/internet/availability/", timeout=30000)
            await page.wait_for_timeout(4000)
            try:
                cookie_btn = page.locator('button:has-text("Continue without changes"), button:has-text("Opt out")').first
                if await cookie_btn.count() > 0:
                    await cookie_btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass
            await page.evaluate("window.scrollTo(0, 500)")
            await page.wait_for_timeout(1500)
            await page.screenshot(path="C:\\xtrategy-fiber\\debug_1.png")
            address_input = await page.wait_for_selector(
                'input[placeholder*="Main st" i], input[placeholder*="address" i], input[id*="address" i]',
                timeout=15000
            )
            await address_input.click()
            await address_input.click(click_count=3)
            await address_input.fill("")
            await page.wait_for_timeout(300)
            await address_input.type(address, delay=80)
            await page.wait_for_timeout(3000)
            await page.screenshot(path="C:\\xtrategy-fiber\\debug_2.png")
            suggestion = page.locator('[role="option"], [class*="suggestion" i], [class*="pac-item" i]').first
            if await suggestion.count() > 0:
                await suggestion.click()
                await page.wait_for_timeout(1500)
            else:
                await address_input.press("ArrowDown")
                await page.wait_for_timeout(500)
                await address_input.press("Enter")
                await page.wait_for_timeout(1500)
            btn = page.locator('button:has-text("Check availability"), button:has-text("Check Availability")').first
            if await btn.count() > 0:
                await btn.click()
            await page.wait_for_timeout(12000)
            await page.screenshot(path="C:\\xtrategy-fiber\\debug_3.png")
            current_url = page.url
            content = (await page.content()).lower()
            print(f"URL: {current_url}")
            no_fiber = ["growing our home internet", "notify me", "internet air is available at your address", "be the first to know"]
            fiber = ["fiber® is available", "fiber is available", "choose your plan", "300mbps speed", "500mbps speed", "1 gig speed", "select this plan"]
            for kw in no_fiber:
                if kw in content:
                    print(f"No fiber: {kw}")
                    return "no_fiber"
            for kw in fiber:
                if kw in content:
                    print(f"Fiber: {kw}")
                    return "fiber"
            return "no_fiber"
        except Exception as e:
            print(f"Error: {e}")
            return "error"
        finally:
            await browser.close()


def add_tag(contact_id, tag):
    url = f"https://services.leadconnectorhq.com/contacts/{contact_id}/tags"
    headers = {"Authorization": f"Bearer {GHL_API_KEY}", "Content-Type": "application/json", "Version": "2021-07-28"}
    resp = requests.post(url, json={"tags": [tag]}, headers=headers)
    print(f"Tag: {resp.status_code} {resp.text}")
    return resp.status_code == 200


def get_contact(contact_id):
    url = f"https://services.leadconnectorhq.com/contacts/{contact_id}"
    headers = {"Authorization": f"Bearer {GHL_API_KEY}", "Version": "2021-07-28"}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        return resp.json().get("contact", {})
    print(f"Error contacto: {resp.status_code} {resp.text}")
    return None


@app.route("/verify-fiber", methods=["POST"])
def verify_fiber():
    data = request.json or {}
    contact_id = data.get("contact_id") or data.get("id")
    if not contact_id:
        return jsonify({"error": "contact_id requerido"}), 400
    contact = get_contact(contact_id)
    if not contact:
        return jsonify({"error": "Contacto no encontrado"}), 404
    address = contact.get("address1", "").strip()
    city = contact.get("city", "").strip()
    state = contact.get("state", "").strip()
    postal = contact.get("postalCode", "").strip()
    if not address:
        return jsonify({"error": "Direccion vacia"}), 400
    full_address = address
    if city: full_address += f", {city}"
    if state: full_address += f", {state}"
    if postal: full_address += f" {postal}"
    print(f"Verificando: {full_address}")
    result = asyncio.run(check_att_fiber(full_address))
    tag = TAG_FIBER if result == "fiber" else TAG_NO_FIBER
    tag_ok = add_tag(contact_id, tag)
    return jsonify({"contact_id": contact_id, "address": full_address, "result": result, "tag": tag, "tag_applied": tag_ok})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
