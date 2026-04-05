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
                if kw
