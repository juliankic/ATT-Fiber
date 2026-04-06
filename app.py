import os
import asyncio
from flask import Flask, request, jsonify
from playwright.async_api import async_playwright
import requests

app = Flask(__name__)

GHL_API_KEY = os.environ.get("GHL_API_KEY", "pit-08166086-17f2-4dcc-88d2-8f065adae15c")
GHL_LOCATION_ID = os.environ.get("GHL_LOCATION_ID", "6VJ6jJ4IxhkiJLzHZUcx")

TAG_FIBER    = "fiber-eligible"
TAG_NO_FIBER = "no-coverage"
TAG_AIR      = "internet-air-eligible"
TAG_EXISTING = "existing-account"


async def wait_for_att_result(page, timeout_ms=25000):
    """
    Espera hasta que la URL de AT&T llegue a su estado final.
    AT&T siempre termina en una de estas URLs:
      - /buy/internet/not-available   -> sin cobertura
      - /buy/internet/plans           -> fibra o air disponible
      - /buy/internet/plans?address_id=XXX -> fibra (variante)
    """
    start = asyncio.get_event_loop().time()

    while True:
        await asyncio.sleep(1)
        current_url = page.url
        elapsed = (asyncio.get_event_loop().time() - start) * 1000

        if "not-available" in current_url:
            await page.wait_for_timeout(2000)
            print(f"Navigation settled at not-available ({elapsed:.0f}ms)")
            return current_url

        if "/buy/internet/plans" in current_url:
            await page.wait_for_timeout(4000)
            print(f"Navigation settled at plans ({elapsed:.0f}ms)")
            return current_url

        if elapsed > timeout_ms:
            print(f"Navigation timeout after {elapsed:.0f}ms, url={current_url}")
            return current_url


async def check_att_fiber(address: str) -> dict:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        existing_account = False

        try:
            await page.goto("https://www.att.com/internet/availability/", timeout=30000)
            await page.wait_for_timeout(4000)

            # Dismiss cookie banners
            try:
                cookie_btn = page.locator(
                    'button:has-text("Continue without changes"), button:has-text("Opt out")'
                ).first
                if await cookie_btn.count() > 0:
                    await cookie_btn.click()
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            await page.evaluate("window.scrollTo(0, 500)")
            await page.wait_for_timeout(1500)
            await page.screenshot(path="/tmp/debug_1.png")

            # Ingresar direccion
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
            await page.screenshot(path="/tmp/debug_2.png")

            # Autocomplete
            suggestion = page.locator(
                '[role="option"], [class*="suggestion" i], [class*="pac-item" i]'
            ).first
            if await suggestion.count() > 0:
                await suggestion.click()
                await page.wait_for_timeout(1500)
            else:
                await address_input.press("ArrowDown")
                await page.wait_for_timeout(500)
                await address_input.press("Enter")
                await page.wait_for_timeout(1500)

            # Click Check availability
            btn = page.locator(
                'button:has-text("Check availability"), button:has-text("Check Availability")'
            ).first
            if await btn.count() > 0:
                await btn.click()

            # Esperar URL final — NO timeout fijo
            await page.screenshot(path="/tmp/debug_3_pre_wait.png")
            final_url = await wait_for_att_result(page, timeout_ms=30000)
            await page.screenshot(path="/tmp/debug_3_post_wait.png")

            # MODAL 1: "We couldn't pinpoint your address"
            pinpoint_modal = page.locator("text=We couldn't pinpoint your address")
            if await pinpoint_modal.count() > 0:
                print("Modal detected: address disambiguation")
                await page.screenshot(path="/tmp/debug_modal_pinpoint.png")

                dropdown_trigger = page.locator('[role="combobox"]').first
                if await dropdown_trigger.count() > 0:
                    await dropdown_trigger.click()
                    await page.wait_for_timeout(1000)

                first_option = page.locator('[role="option"]').first
                if await first_option.count() > 0:
                    option_text = await first_option.inner_text()
                    print(f"Selecting first address: {option_text.strip()}")
                    await first_option.click()
                    await page.wait_for_timeout(1000)

                continue_btn = page.locator('button:has-text("Continue")').first
                if await continue_btn.count() > 0:
                    await continue_btn.click()
                    print("Clicked Continue on address modal")
                    final_url = await wait_for_att_result(page, timeout_ms=25000)
                    await page.screenshot(path="/tmp/debug_after_pinpoint.png")

            # MODAL 2: "We found an existing AT&T account at this address"
            existing_modal = page.locator("text=We found an existing AT&T account at this address")
            if await existing_modal.count() > 0:
                print("Modal detected: existing AT&T account")
                existing_account = True
                await page.screenshot(path="/tmp/debug_modal_existing.png")

                modal_content = (await page.content()).lower()
                modal_has_fiber = any(phrase in modal_content for phrase in [
                    "great news! at&t fiber",
                    "great news! at&t fiber\u00ae",
                ])
                if modal_has_fiber:
                    print("Modal title confirms: fiber available")

                new_btn = page.locator("button:has-text(\"No, I'm new to AT&T\")").first
                if await new_btn.count() > 0:
                    await new_btn.click()
                    print("Clicked 'No, I'm new to AT&T'")
                    await page.wait_for_timeout(6000)
                    final_url = page.url
                    await page.screenshot(path="/tmp/debug_after_existing.png")
                else:
                    if modal_has_fiber:
                        print("Result: fiber (modal confirmed, button not found)")
                        return {"coverage": "fiber", "existing_account": True}

            # Leer estado final
            current_url = page.url
            content = (await page.content()).lower()
            print(f"URL final: {current_url}")

            # REGLA 1: URL not-available = sin cobertura (regla mas confiable)
            if "not-available" in current_url:
                print("Result: none (URL = not-available)")
                return {"coverage": "none", "existing_account": existing_account}

            # REGLA 2: Textos de no cobertura
            no_coverage_phrases = [
                "give us a call to see if home internet",
                "growing our home internet",
                "be the first to know",
                "not available at your address",
                "not available in your area",
                "we're working to bring",
                "we don't offer service",
            ]
            for phrase in no_coverage_phrases:
                if phrase in content:
                    print(f"Result: none (phrase: '{phrase}')")
                    return {"coverage": "none", "existing_account": existing_account}

            # REGLA 3: Fiber CONFIRMADO
            fiber_confirmed_phrases = [
                "great news! at&t fiber\u00ae is available",
                "great news! at&t fiber is available",
                "great news! att fiber is available",
                "at&t fiber\u00ae is available at",
                "at&t fiber is available at",
                "att fiber is available",
                "fiber internet is available",
            ]
            for phrase in fiber_confirmed_phrases:
                if phrase in content:
                    print(f"Result: fiber (confirmed: '{phrase}')")
                    return {"coverage": "fiber", "existing_account": existing_account}

            # REGLA 4: Internet Air CONFIRMADO
            air_confirmed_phrases = [
                "great news! at&t internet air",
                "great news! att internet air",
                "at&t internet air is available",
                "att internet air is available",
                "internet air is available",
                "wireless home internet is available",
                "fixed wireless is available",
            ]
            for phrase in air_confirmed_phrases:
                if phrase in content:
                    print(f"Result: air (confirmed: '{phrase}')")
                    return {"coverage": "air", "existing_account": existing_account}

            # REGLA 5: Planes de fibra visibles
            fiber_speed_keywords = [
                "300mbps speed",
                "500mbps speed",
                "up to 1 gig speed",
                "1 gig speed",
                "2 gig speed",
                "5 gig speed",
                "100mbps speed",
            ]
            has_fiber_speed = any(kw in content for kw in fiber_speed_keywords)
            has_price = "/mo" in content or "per month" in content
            fiber_word_count = content.count("fiber")
            has_air_mention = any(kw in content for kw in [
                "internet air", "wireless home internet", "fixed wireless"
            ])

            if has_fiber_speed and has_price and fiber_word_count >= 3:
                print(f"Result: fiber (speed+price, fiber_count={fiber_word_count})")
                return {"coverage": "fiber", "existing_account": existing_account}

            # REGLA 6: Internet Air
            if has_air_mention and "great news" in content and not has_fiber_speed:
                print("Result: air (great news + air, no fiber speeds)")
                return {"coverage": "air", "existing_account": existing_account}

            # FALLBACK
            print(f"Result: none (fallback, fiber_count={fiber_word_count})")
            return {"coverage": "none", "existing_account": existing_account}

        except Exception as e:
            print(f"Error: {e}")
            return {"coverage": "error", "existing_account": existing_account}
        finally:
            await browser.close()


def add_tag(contact_id, tag):
    url = f"https://services.leadconnectorhq.com/contacts/{contact_id}/tags"
    headers = {
        "Authorization": f"Bearer {GHL_API_KEY}",
        "Content-Type": "application/json",
        "Version": "2021-07-28"
    }
    resp = requests.post(url, json={"tags": [tag]}, headers=headers)
    print(f"Tag '{tag}': {resp.status_code} {resp.text}")
    return resp.status_code == 200


def get_contact(contact_id):
    url = f"https://services.leadconnectorhq.com/contacts/{contact_id}"
    headers = {
        "Authorization": f"Bearer {GHL_API_KEY}",
        "Version": "2021-07-28"
    }
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
    city    = contact.get("city", "").strip()
    state   = contact.get("state", "").strip()
    postal  = contact.get("postalCode", "").strip()

    if not address:
        return jsonify({"error": "Direccion vacia"}), 400

    full_address = address
    if city:   full_address += f", {city}"
    if state:  full_address += f", {state}"
    if postal: full_address += f" {postal}"

    print(f"Verificando: {full_address}")
    result = asyncio.run(check_att_fiber(full_address))

    coverage = result["coverage"]
    existing = result["existing_account"]
    tags_applied = []

    if coverage == "fiber":
        if add_tag(contact_id, TAG_FIBER):
            tags_applied.append(TAG_FIBER)
    elif coverage == "air":
        if add_tag(contact_id, TAG_AIR):
            tags_applied.append(TAG_AIR)
    else:
        if add_tag(contact_id, TAG_NO_FIBER):
            tags_applied.append(TAG_NO_FIBER)

    if existing:
        if add_tag(contact_id, TAG_EXISTING):
            tags_applied.append(TAG_EXISTING)

    return jsonify({
        "contact_id":       contact_id,
        "address":          full_address,
        "coverage":         coverage,
        "existing_account": existing,
        "tags_applied":     tags_applied
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
