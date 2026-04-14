import os
import re
import json
import csv
import io
import time
import random
import asyncio
import threading
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from . import scraper_bp
from extensions import db
from models import ScraperLead, Lead

try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

import requests as http_requests
from bs4 import BeautifulSoup

# ── Per-user scraper status ────────────────────────────────────────────────────
_user_status = {}  # user_id -> status dict


def get_status(user_id):
    return _user_status.get(user_id, {"message": "Idle", "running": False, "progress": 0, "total": 0})


def set_status(user_id, msg, progress=None, total=None):
    s = _user_status.setdefault(user_id, {"message": "Idle", "running": False, "progress": 0, "total": 0})
    s["message"] = msg
    if progress is not None:
        s["progress"] = progress
    if total is not None:
        s["total"] = total
    print(f"[Scraper:{user_id}] {msg}")


# ── Location Presets ────────────────────────────────────────────────────────────
LOCATION_PRESETS = {
    "Mid-Atlantic": {
        "Philadelphia Area": ["Philadelphia PA", "Norristown PA", "King of Prussia PA", "West Chester PA"],
        "South Jersey": ["Cherry Hill NJ", "Voorhees NJ", "Marlton NJ", "Mount Laurel NJ"],
        "Delaware Valley": ["Wilmington DE", "Newark DE", "Dover DE"],
        "Baltimore Area": ["Baltimore MD", "Towson MD", "Columbia MD", "Annapolis MD"],
        "DC Suburbs": ["Bethesda MD", "Rockville MD", "Alexandria VA", "Arlington VA"],
    },
    "Northeast": {
        "New York Metro": ["Manhattan NY", "Brooklyn NY", "Queens NY", "Yonkers NY"],
        "Long Island": ["Garden City NY", "Huntington NY", "Babylon NY"],
        "North Jersey": ["Newark NJ", "Jersey City NJ", "Hoboken NJ", "Hackensack NJ"],
        "Connecticut": ["Hartford CT", "New Haven CT", "Stamford CT"],
        "Boston Area": ["Boston MA", "Cambridge MA", "Newton MA", "Worcester MA"],
    },
    "Midwest": {
        "Chicago Area": ["Chicago IL", "Naperville IL", "Aurora IL", "Schaumburg IL"],
        "Detroit Area": ["Detroit MI", "Dearborn MI", "Ann Arbor MI", "Troy MI"],
        "Columbus Area": ["Columbus OH", "Dublin OH", "Westerville OH"],
        "Minneapolis Area": ["Minneapolis MN", "Saint Paul MN", "Bloomington MN"],
    },
    "South": {
        "Atlanta Area": ["Atlanta GA", "Alpharetta GA", "Marietta GA", "Roswell GA"],
        "Dallas Area": ["Dallas TX", "Fort Worth TX", "Plano TX", "Irving TX"],
        "Houston Area": ["Houston TX", "Sugar Land TX", "Pearland TX"],
        "Charlotte Area": ["Charlotte NC", "Concord NC", "Gastonia NC"],
        "Nashville Area": ["Nashville TN", "Murfreesboro TN", "Franklin TN"],
        "Miami Area": ["Miami FL", "Coral Gables FL", "Hialeah FL"],
    },
    "West": {
        "Los Angeles Area": ["Los Angeles CA", "Burbank CA", "Pasadena CA", "Glendale CA"],
        "San Francisco Bay": ["San Francisco CA", "Oakland CA", "San Jose CA"],
        "Seattle Area": ["Seattle WA", "Bellevue WA", "Tacoma WA", "Kirkland WA"],
        "Phoenix Area": ["Phoenix AZ", "Scottsdale AZ", "Mesa AZ", "Tempe AZ"],
        "Denver Area": ["Denver CO", "Aurora CO", "Lakewood CO", "Arvada CO"],
    },
}

ALL_INDUSTRIES = [
    ("restaurant", "Restaurant / Bar / Cafe"),
    ("hvac", "HVAC / Heating & Cooling"),
    ("plumbing", "Plumbing"),
    ("construction", "Construction / Contractor"),
    ("landscaping", "Landscaping / Lawn Care"),
    ("manufacturing", "Manufacturing"),
    ("auto", "Auto Shop / Mechanic"),
    ("dental", "Dental / Orthodontics"),
    ("veterinary", "Veterinary Clinic"),
    ("fitness", "Gym / Fitness Studio"),
    ("medspa", "Med Spa / Salon"),
    ("law", "Law Firm"),
    ("accounting", "Accounting / CPA"),
    ("insurance", "Insurance Agency"),
    ("mortgage", "Mortgage / Finance"),
    ("real_estate", "Real Estate"),
    ("retail", "Retail / Boutique"),
    ("trucking", "Trucking / Logistics"),
    ("property_management", "Property Management"),
    ("default", "Other / Custom"),
]

INDUSTRY_SEARCH_TERMS = {
    "restaurant": "restaurant", "hvac": "HVAC heating cooling",
    "plumbing": "plumbing company", "construction": "construction contractor",
    "landscaping": "landscaping lawn care", "manufacturing": "manufacturing company",
    "auto": "auto repair shop", "dental": "dental office",
    "veterinary": "veterinary clinic", "fitness": "gym fitness studio",
    "medspa": "med spa salon", "law": "law firm attorney",
    "accounting": "accounting CPA", "insurance": "insurance agency",
    "mortgage": "mortgage lender", "real_estate": "real estate agency",
    "retail": "retail store", "trucking": "trucking logistics",
    "property_management": "property management company",
}

INDUSTRY_PRICING = {
    "restaurant": {"small": {"setup": 800, "monthly": 250, "label": "Basic chatbot + reservation handling"}, "mid": {"setup": 1500, "monthly": 400, "label": "Catering automation + review responses"}, "large": {"setup": 3000, "monthly": 700, "label": "Full customer comms automation"}},
    "hvac": {"small": {"setup": 1000, "monthly": 300, "label": "Scheduling + after-hours answering"}, "mid": {"setup": 2000, "monthly": 500, "label": "Scheduling + estimate follow-ups"}, "large": {"setup": 4000, "monthly": 900, "label": "Full workflow automation"}},
    "default": {"small": {"setup": 1000, "monthly": 300, "label": "Custom AI automation"}, "mid": {"setup": 2000, "monthly": 500, "label": "Custom AI automation"}, "large": {"setup": 4000, "monthly": 900, "label": "Custom AI automation"}},
}

INDUSTRY_CONTEXT = {
    "restaurant": "Focus on: reservation and catering inquiry handling, private dining follow-ups, review management.",
    "hvac": "Focus on: after-hours call handling, scheduling, estimate follow-ups.",
    "manufacturing": "Focus on: quote follow-up, order status updates, customer communication admin.",
    "law": "Focus on: new client intake, consult scheduling, follow-ups on initial inquiries.",
    "default": "Focus on: the most obvious manual processes that AI could automate based on their website content.",
}

EMAIL_VARIANTS = {
    "A": {"style": "Direct problem opener — lead immediately with the specific operational problem.", "signoff": "Best,"},
    "B": {"style": "Curiosity opener — open with a short punchy question or observation.", "signoff": "Thanks,"},
    "C": {"style": "Social proof opener — briefly reference working with similar businesses.", "signoff": "Talk soon,"},
    "D": {"style": "Industry insider opener — show you understand their industry specifically.", "signoff": "Appreciate your time,"},
}

EVAN_STYLE_GUIDE = """EMAIL RULES:
- Open with "Hi," on its own line, blank line, then first sentence
- 4-6 sentences. Casual, direct, sounds human. No bullets or lists
- First sentence: specific and real about their business. No flattery.
- Sign-off word on one line, first name only on next line.
- NEVER use: hyphens/dashes, "utilize", "I hope this finds you well", "touch base"
- NEVER fabricate dollar amounts or stats not provided"""

REAL_STATS = [
    "businesses that automate customer communications typically reclaim 6 to 10 hours per employee per week according to McKinsey",
    "research from Harvard Business Review shows responding to a lead within 5 minutes makes you 9 times more likely to close versus waiting 30 minutes",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36",
]


def rnd_headers():
    return {"User-Agent": random.choice(USER_AGENTS), "Accept-Language": "en-US,en;q=0.9", "DNT": "1"}


def detect_industry(text):
    text = (text or "").lower()
    if any(w in text for w in ["restaurant", "bar", "cafe", "diner", "pizza", "food", "dining"]): return "restaurant"
    if any(w in text for w in ["hvac", "heating", "cooling", "air condition", "furnace"]): return "hvac"
    if any(w in text for w in ["plumb", "drain", "pipe", "sewer"]): return "plumbing"
    if any(w in text for w in ["manufactur", "assembly", "fabricat", "machine shop"]): return "manufacturing"
    if any(w in text for w in ["law", "attorney", "legal", "counsel", "litigation"]): return "law"
    if any(w in text for w in ["construct", "contractor", "builder", "remodel", "roofing"]): return "construction"
    if any(w in text for w in ["dental", "dentist", "orthodont", "oral"]): return "dental"
    if any(w in text for w in ["auto", "car", "mechanic", "tire", "collision"]): return "auto"
    if any(w in text for w in ["real estate", "realtor", "realty", "broker"]): return "real_estate"
    if any(w in text for w in ["landscape", "lawn", "mow", "turf", "irrigation"]): return "landscaping"
    if any(w in text for w in ["account", "cpa", "tax", "bookkeep", "payroll"]): return "accounting"
    if any(w in text for w in ["gym", "fitness", "crossfit", "yoga", "pilates"]): return "fitness"
    if any(w in text for w in ["insurance", "agency", "coverage", "policy"]): return "insurance"
    if any(w in text for w in ["mortgage", "loan", "lender", "refinanc"]): return "mortgage"
    if any(w in text for w in ["med spa", "medspa", "botox", "filler", "salon"]): return "medspa"
    if any(w in text for w in ["veterinar", "vet clinic", "animal hospital"]): return "veterinary"
    if any(w in text for w in ["truck", "freight", "logistics", "carrier", "dispatch"]): return "trucking"
    if any(w in text for w in ["property management", "property manager", "landlord", "rental"]): return "property_management"
    return "default"


def detect_size(review_count, website_text):
    text = (website_text or "").lower()
    reviews = 0
    try:
        reviews = int(str(review_count).replace(",", ""))
    except Exception:
        pass
    multi = any(w in text for w in ["locations", "branches", "offices", "nationwide", "franchise"])
    if multi or reviews > 200:
        return "large"
    if reviews > 50:
        return "mid"
    return "small"


def estimate_revenue(industry, size="mid"):
    tiers = INDUSTRY_PRICING.get(industry, INDUSTRY_PRICING["default"])
    p = tiers.get(size, tiers["mid"])
    annual = p["setup"] + (p["monthly"] * 12)
    return {"setup": p["setup"], "monthly": p["monthly"], "annual_value": annual, "label": p["label"], "size": size}


def scrape_website(url):
    if not url or not url.startswith("http"):
        return ""
    try:
        resp = http_requests.get(url, headers=rnd_headers(), timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "head"]):
            tag.decompose()
        return " ".join(soup.stripped_strings)[:3000]
    except Exception:
        return ""


def find_email_in_text(text):
    skip = {"example.com", "domain.com", "email.com", "sentry.io", "wix.com",
            "wordpress.com", "schema.org", "w3.org", "google.com", "facebook.com"}
    for e in re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text):
        domain = e.split("@")[-1].lower()
        if domain not in skip and not domain[0].isdigit():
            return e
    return ""


def find_email(website_text, website_url=""):
    email = find_email_in_text(website_text)
    if email:
        return email
    if not website_url or not website_url.startswith("http"):
        return ""
    base = website_url.rstrip("/")
    subpages = ["/contact", "/contact-us", "/about", "/about-us", "/team", "/get-in-touch"]
    for path in subpages:
        try:
            resp = http_requests.get(base + path, headers=rnd_headers(), timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.select("a[href^='mailto:']"):
                    href = a.get("href", "").replace("mailto:", "").split("?")[0].strip()
                    if href and "@" in href:
                        domain = href.split("@")[-1].lower()
                        if domain not in {"example.com", "domain.com", "wix.com"}:
                            return href
                for tag in soup(["script", "style", "nav", "footer"]):
                    tag.decompose()
                text = " ".join(soup.stripped_strings)
                email = find_email_in_text(text)
                if email:
                    return email
        except Exception:
            continue
    return ""


def classify_email(email):
    if not email:
        return "none", "No Email"
    local = email.split("@")[0].lower()
    generic = {"info", "contact", "hello", "admin", "office", "mail", "support", "help",
               "sales", "team", "staff", "service", "reception", "general", "marketing",
               "billing", "accounts", "bookings", "orders", "noreply", "no-reply"}
    if local in generic:
        return "generic", "Generic"
    for prefix in generic:
        if local.startswith(prefix) and (len(local) == len(prefix) or not local[len(prefix)].isalpha()):
            return "generic", "Generic"
    return "personal", "Personal"


async def _scrape_google_maps_async(niche, location, max_results=20, radius_miles=10, user_id=None):
    if radius_miles <= 10:
        query = f"{niche} near {location}"
    else:
        query = f"{niche} near {location} within {radius_miles} miles"

    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = await ctx.new_page()
        url = f"https://www.google.com/maps/search/{http_requests.utils.quote(query)}"
        if user_id:
            set_status(user_id, f"Google Maps: {query}")

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_selector('div[role="feed"]', timeout=15000)
            except Exception:
                pass
            await page.wait_for_timeout(2000)

            for _ in range(max(3, max_results // 4)):
                try:
                    await page.locator('div[role="feed"]').evaluate("el => el.scrollTop += 1000")
                    await page.wait_for_timeout(800)
                except Exception:
                    pass

            cards = await page.locator('div[role="feed"] a[href*="/maps/place/"]').all()
            seen = set()
            for card in cards:
                if len(results) >= max_results:
                    break
                try:
                    parent = card.locator("xpath=../..")
                    text = await asyncio.wait_for(asyncio.ensure_future(parent.inner_text()), timeout=4)
                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    if not lines:
                        continue
                    name = lines[0]
                    if not name or name in seen or len(name) < 2:
                        continue
                    seen.add(name)

                    await asyncio.wait_for(asyncio.ensure_future(card.click()), timeout=4)
                    await page.wait_for_timeout(1200)

                    address = phone = website = rating = reviews = ""

                    for sel in ['button[data-item-id="address"] .Io6YTe', '[data-item-id="address"] .fontBodyMedium']:
                        try:
                            el = page.locator(sel).first
                            if await el.count() and await asyncio.wait_for(asyncio.ensure_future(el.is_visible()), timeout=2):
                                address = (await asyncio.wait_for(asyncio.ensure_future(el.inner_text()), timeout=2)).strip()
                                break
                        except Exception:
                            pass

                    for sel in ['button[data-item-id*="phone"] .Io6YTe', 'button[aria-label*="Phone"] .Io6YTe']:
                        try:
                            el = page.locator(sel).first
                            if await el.count() and await asyncio.wait_for(asyncio.ensure_future(el.is_visible()), timeout=2):
                                phone = (await asyncio.wait_for(asyncio.ensure_future(el.inner_text()), timeout=2)).strip()
                                break
                        except Exception:
                            pass

                    for sel in ['a[data-item-id="authority"]', 'a[aria-label*="website" i]', 'a.CsEnBe[href^="http"]']:
                        try:
                            el = page.locator(sel).first
                            if await el.count() and await asyncio.wait_for(asyncio.ensure_future(el.is_visible()), timeout=2):
                                href = await asyncio.wait_for(asyncio.ensure_future(el.get_attribute("href")), timeout=2) or ""
                                if href.startswith("http") and "google.com" not in href:
                                    website = href
                                    break
                        except Exception:
                            pass

                    try:
                        el = page.locator('div.F7nice span[aria-hidden="true"]').first
                        if await el.count():
                            rating = (await asyncio.wait_for(asyncio.ensure_future(el.inner_text()), timeout=2)).strip()
                    except Exception:
                        pass
                    try:
                        el = page.locator('div.F7nice span[aria-label*="review"]').first
                        if await el.count():
                            aria = await asyncio.wait_for(asyncio.ensure_future(el.get_attribute("aria-label")), timeout=2) or ""
                            reviews = re.sub(r"[^\d]", "", aria)
                    except Exception:
                        pass

                    results.append({"name": name, "address": address, "phone": phone,
                                    "website": website, "rating": rating, "reviews": reviews, "source": "google_maps"})
                    if user_id:
                        set_status(user_id, f"Google Maps: {len(results)} leads extracted")

                    try:
                        await asyncio.wait_for(asyncio.ensure_future(page.go_back(wait_until="domcontentloaded")), timeout=4)
                        await page.wait_for_timeout(600)
                    except Exception:
                        pass
                except Exception:
                    continue
        except Exception as e:
            if user_id:
                set_status(user_id, f"Google Maps error: {e}")
        finally:
            await browser.close()

    return results[:max_results]


async def _scrape_yellowpages_async(niche, location, max_results=20, user_id=None):
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}, locale="en-US",
        )
        page = await ctx.new_page()
        try:
            for pg in range(1, 4):
                if len(results) >= max_results:
                    break
                url = f"https://www.yellowpages.com/search?search_terms={http_requests.utils.quote(niche)}&geo_location_terms={http_requests.utils.quote(location)}&page={pg}"
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_timeout(2000)
                except Exception:
                    break

                content = await page.content()
                soup = BeautifulSoup(content, "html.parser")
                listings = soup.select("div.result, div.v-card")
                if not listings:
                    break

                for listing in listings:
                    if len(results) >= max_results:
                        break
                    name_el = listing.select_one("a.business-name, h2.n span, .business-name span")
                    if not name_el:
                        continue
                    name = name_el.get_text(strip=True)
                    if not name:
                        continue

                    phone_el = listing.select_one(".phones.phone.primary, .phone")
                    street_el = listing.select_one(".street-address")
                    city_el = listing.select_one(".locality")
                    website_el = listing.select_one("a.track-visit-website, a[data-analytics='website']")

                    address = " ".join(filter(None, [
                        street_el.get_text(strip=True) if street_el else "",
                        city_el.get_text(strip=True) if city_el else "",
                    ]))

                    website = ""
                    if website_el:
                        href = website_el.get("href", "")
                        match = re.search(r'url=([^&]+)', href)
                        if match:
                            from urllib.parse import unquote
                            website = unquote(match.group(1))
                        elif href.startswith("http"):
                            website = href

                    results.append({"name": name, "address": address or location,
                                    "phone": phone_el.get_text(strip=True) if phone_el else "",
                                    "website": website, "rating": "", "reviews": "", "source": "yellowpages"})
        except Exception as e:
            if user_id:
                set_status(user_id, f"Yellow Pages error: {e}")
        finally:
            await browser.close()
    return results[:max_results]


def scrape_leads(niche, location, max_results=20, radius_miles=10, user_id=None):
    gm_target = max(10, int(max_results * 0.75))
    yp_target = max_results - gm_target

    gm_results = []
    if PLAYWRIGHT_OK:
        for radius in [radius_miles, 25, 50]:
            if radius < radius_miles:
                continue
            try:
                gm_results = asyncio.run(_scrape_google_maps_async(niche, location, gm_target, radius, user_id))
            except Exception as e:
                if user_id:
                    set_status(user_id, f"Google Maps error: {e}")
            if len(gm_results) >= gm_target:
                break

    shortfall = max(0, gm_target - len(gm_results))
    yp_target += shortfall
    yp_results = []
    if PLAYWRIGHT_OK:
        try:
            yp_results = asyncio.run(_scrape_yellowpages_async(niche, location, yp_target, user_id))
        except Exception as e:
            if user_id:
                set_status(user_id, f"Yellow Pages error: {e}")

    combined = gm_results + yp_results
    seen_names = set()
    seen_phones = set()
    deduped = []
    for lead in combined:
        name = lead.get("name", "").strip().lower()
        phone = re.sub(r"\D", "", lead.get("phone", ""))
        if name in seen_names:
            continue
        if phone and len(phone) >= 7 and phone in seen_phones:
            continue
        seen_names.add(name)
        if phone and len(phone) >= 7:
            seen_phones.add(phone)
        deduped.append(lead)

    return deduped[:max_results]


def ai_score_and_email(lead, website_text, api_key, variant_key="A", your_name="Evan", your_company="FlowState AI", calendly_link="", email_threshold=6):
    import anthropic as anthropic_lib
    client = anthropic_lib.Anthropic(api_key=api_key)
    industry = detect_industry((lead.get("query", "") + " " + lead.get("name", "") + " " + website_text))
    size = detect_size(lead.get("reviews", "0"), website_text)
    ind_context = INDUSTRY_CONTEXT.get(industry, INDUSTRY_CONTEXT["default"])

    score_prompt = f"""Score this business as a cold outreach target for AI automation services.

Business: {lead['name']}
Rating: {lead.get('rating', '')} ({lead.get('reviews', '')} reviews)
Industry: {industry}
Website snippet: {website_text[:800] if website_text else '[none]'}

Respond ONLY with valid JSON, no markdown:
{{
  "score": <1-10>,
  "reasoning": "<1 sentence why>",
  "pain_points": ["<pain 1>", "<pain 2>"],
  "owner_reachable": <true|false>
}}"""

    score_result = {"score": 0, "reasoning": "", "pain_points": [], "owner_reachable": False}
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": score_prompt}]
        )
        raw = re.sub(r"^```json\s*|\s*```$", "", resp.content[0].text.strip(), flags=re.MULTILINE).strip()
        score_result = json.loads(raw)
    except Exception as e:
        score_result["reasoning"] = f"Score error: {e}"

    score = score_result.get("score", 0)
    rev = estimate_revenue(industry, size)
    result = {
        "score": score,
        "reasoning": score_result.get("reasoning", ""),
        "pain_points": score_result.get("pain_points", []),
        "owner_reachable": score_result.get("owner_reachable", False),
        "variant": variant_key,
        "industry": industry,
        "biz_size": size,
        "revenue_setup": rev["setup"],
        "revenue_monthly": rev["monthly"],
        "revenue_annual": rev["annual_value"],
        "revenue_label": rev["label"],
        "email_subject": "",
        "email_body": "",
    }

    if score >= email_threshold:
        variant = EMAIL_VARIANTS.get(variant_key, EMAIL_VARIANTS["A"])
        stat = random.choice(REAL_STATS)
        cal_line = f"\n{calendly_link}" if calendly_link else ""

        email_prompt = f"""Write a cold outreach email for {your_name} at {your_company}.

Business: {lead['name']} ({industry}, {lead.get('address', '')})
Rating: {lead.get('rating', '')} ({lead.get('reviews', '')} reviews)
Pain points: {', '.join(score_result.get('pain_points', []))}
Industry context: {ind_context}
Website content: {website_text[:1200] if website_text else '[none]'}

{EVAN_STYLE_GUIDE}

Variant {variant_key}: {variant['style']}
Sign-off: {variant['signoff']} then {your_name} on next line.
Stat (use only if natural): {stat}
Calendly: {cal_line}

Respond ONLY with valid JSON, no markdown:
{{
  "email_subject": "<under 55 chars, sounds human>",
  "email_body": "<full email>"
}}"""

        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=700,
                messages=[{"role": "user", "content": email_prompt}]
            )
            raw = re.sub(r"^```json\s*|\s*```$", "", resp.content[0].text.strip(), flags=re.MULTILINE).strip()
            email_result = json.loads(raw)
            result["email_subject"] = email_result.get("email_subject", "")
            result["email_body"] = email_result.get("email_body", "")
        except Exception as e:
            result["email_body"] = f"[Email generation error: {e}]"

    return result


def run_pipeline(app, user_id, query, max_results, api_key, auto_send, cities=None, location=None, radius=10,
                 your_name="Evan", your_company="FlowState AI", calendly_link="", email_threshold=6,
                 gmail_address="", gmail_password="", personal_only=False):
    with app.app_context():
        _user_status[user_id] = {"message": "Starting...", "running": True, "progress": 0, "total": 0}
        leads_out = []

        try:
            niche = query.strip()
            loc = location or (cities[0] if cities else "United States")

            all_raw = []
            if cities:
                per_city = max(5, max_results // len(cities))
                for city in cities:
                    all_raw += scrape_leads(niche, city, per_city, radius, user_id)
            else:
                all_raw = scrape_leads(niche, loc, max_results, radius, user_id)

            # Deduplicate against existing DB leads for this user
            existing_names = {l.name.strip().lower() for l in ScraperLead.query.filter_by(user_id=user_id).all()}
            existing_phones = {re.sub(r"\D", "", l.phone) for l in ScraperLead.query.filter_by(user_id=user_id).all() if l.phone}

            deduped = []
            for l in all_raw:
                name = l.get("name", "").strip().lower()
                phone = re.sub(r"\D", "", l.get("phone", ""))
                if name in existing_names:
                    continue
                if phone and len(phone) >= 7 and phone in existing_phones:
                    continue
                deduped.append(l)

            all_raw = deduped[:max_results]
            set_status(user_id, f"After deduplication: {len(all_raw)} new businesses")
            _user_status[user_id]["total"] = len(all_raw)

            if not all_raw:
                set_status(user_id, "No new businesses found — try a different niche or location")
                _user_status[user_id]["running"] = False
                return

            for i, lead in enumerate(all_raw):
                set_status(user_id, f"Processing {i+1}/{len(all_raw)}: {lead['name']}", progress=i)
                wtext = scrape_website(lead.get("website", ""))
                lead["email_found"] = find_email(wtext, lead.get("website", ""))
                email_tier, _ = classify_email(lead["email_found"])
                lead["email_tier"] = email_tier
                time.sleep(2 + random.uniform(0, 1.5))

                has_website = bool(lead.get("website"))
                has_email = bool(lead.get("email_found"))

                if not has_website and not has_email:
                    industry = detect_industry(lead.get("name", ""))
                    size = detect_size(lead.get("reviews", "0"), "")
                    rev = estimate_revenue(industry, size)
                    sl = ScraperLead(
                        user_id=user_id,
                        name=lead.get("name", ""),
                        address=lead.get("address", ""),
                        phone=lead.get("phone", ""),
                        website=lead.get("website", ""),
                        rating=lead.get("rating", ""),
                        reviews=lead.get("reviews", ""),
                        source=lead.get("source", ""),
                        email_found="",
                        email_tier="none",
                        query=query,
                        industry=industry,
                        biz_size=size,
                        score=0,
                        reasoning="No website or email found",
                        owner_reachable=False,
                        variant="",
                        revenue_setup=rev["setup"],
                        revenue_monthly=rev["monthly"],
                        revenue_annual=rev["annual_value"],
                        revenue_label=rev["label"],
                        status="low_score",
                        scraped_at=datetime.utcnow(),
                    )
                    sl.pain_points = []
                    db.session.add(sl)
                    db.session.commit()
                    _user_status[user_id]["progress"] = i + 1
                    continue

                variant = random.choice(list(EMAIL_VARIANTS.keys()))
                set_status(user_id, f"AI scoring (Variant {variant}): {lead['name']}")

                if api_key:
                    ai = ai_score_and_email(lead, wtext, api_key, variant, your_name, your_company, calendly_link, email_threshold)
                else:
                    industry = detect_industry(lead.get("name", ""))
                    size = detect_size(lead.get("reviews", "0"), wtext)
                    rev = estimate_revenue(industry, size)
                    ai = {"score": 5, "reasoning": "No API key set", "pain_points": [], "owner_reachable": False,
                          "variant": variant, "industry": industry, "biz_size": size,
                          "revenue_setup": rev["setup"], "revenue_monthly": rev["monthly"],
                          "revenue_annual": rev["annual_value"], "revenue_label": rev["label"],
                          "email_subject": "", "email_body": ""}

                status = "pending"
                if ai["score"] >= email_threshold:
                    status = "ready"
                else:
                    status = "low_score"

                sl = ScraperLead(
                    user_id=user_id,
                    name=lead.get("name", ""),
                    address=lead.get("address", ""),
                    phone=lead.get("phone", ""),
                    website=lead.get("website", ""),
                    rating=lead.get("rating", ""),
                    reviews=lead.get("reviews", ""),
                    source=lead.get("source", ""),
                    email_found=lead.get("email_found", ""),
                    email_tier=lead.get("email_tier", ""),
                    query=query,
                    industry=ai.get("industry", "default"),
                    biz_size=ai.get("biz_size", "mid"),
                    score=ai.get("score", 0),
                    reasoning=ai.get("reasoning", ""),
                    owner_reachable=ai.get("owner_reachable", False),
                    variant=variant,
                    email_subject=ai.get("email_subject", ""),
                    email_body=ai.get("email_body", ""),
                    revenue_setup=ai.get("revenue_setup", 0),
                    revenue_monthly=ai.get("revenue_monthly", 0),
                    revenue_annual=ai.get("revenue_annual", 0),
                    revenue_label=ai.get("revenue_label", ""),
                    status=status,
                    scraped_at=datetime.utcnow(),
                )
                sl.pain_points = ai.get("pain_points", [])
                db.session.add(sl)
                db.session.commit()
                _user_status[user_id]["progress"] = i + 1

            set_status(user_id, f"Done — {len(all_raw)} leads processed.", progress=len(all_raw))

        except Exception as e:
            set_status(user_id, f"Pipeline error: {e}")
        finally:
            _user_status[user_id]["running"] = False


# ── Routes ─────────────────────────────────────────────────────────────────────
@scraper_bp.route('/')
@login_required
def index():
    from crypto_utils import decrypt
    api_key = decrypt(current_user.anthropic_api_key_encrypted) if current_user.anthropic_api_key_encrypted else ''
    return render_template('scraper/index.html',
                           location_presets=LOCATION_PRESETS,
                           all_industries=ALL_INDUSTRIES,
                           has_api_key=bool(api_key))


@scraper_bp.route('/run', methods=['POST'])
@login_required
def run_route():
    status = get_status(current_user.id)
    if status.get("running"):
        return jsonify({"error": "Pipeline already running"}), 400

    data = request.get_json(silent=True) or {}
    from crypto_utils import decrypt
    api_key = decrypt(current_user.anthropic_api_key_encrypted) if current_user.anthropic_api_key_encrypted else ''

    raw_query = (data.get("query", "") or "").strip()
    industry = (data.get("industry", "") or "").strip()
    query = raw_query or INDUSTRY_SEARCH_TERMS.get(industry, industry)
    location = (data.get("location", "") or "").strip()
    cities = data.get("cities", None)
    radius = int(data.get("radius", 10))

    if not query:
        return jsonify({"error": "Please select an industry or type a niche"}), 400
    if not location and not cities:
        return jsonify({"error": "Please enter a location or select a region"}), 400

    your_name = current_user.display_name.split()[0] if current_user.display_name else "Evan"

    from flask import current_app
    app = current_app._get_current_object()

    threading.Thread(
        target=run_pipeline,
        args=(app, current_user.id, query, int(data.get("max_results", 20)), api_key,
              data.get("auto_send", False), cities, location, radius,
              your_name, "FlowState AI", "", 6, "", "", False),
        daemon=True
    ).start()

    return jsonify({"ok": True})


@scraper_bp.route('/status')
@login_required
def status():
    return jsonify(get_status(current_user.id))


@scraper_bp.route('/leads')
@login_required
def get_leads():
    q = request.args.get("q", "").lower()
    s = request.args.get("status", "")
    ind = request.args.get("industry", "")
    tier = request.args.get("email_tier", "")

    query = ScraperLead.query.filter_by(user_id=current_user.id)
    if q:
        query = query.filter(ScraperLead.name.ilike(f"%{q}%"))
    if s:
        query = query.filter_by(status=s)
    if ind:
        query = query.filter_by(industry=ind)
    if tier:
        query = query.filter_by(email_tier=tier)

    leads = query.order_by(ScraperLead.scraped_at.desc()).all()

    return jsonify([{
        "id": l.id,
        "name": l.name,
        "address": l.address,
        "phone": l.phone,
        "website": l.website,
        "email_found": l.email_found,
        "email_tier": l.email_tier,
        "score": l.score,
        "industry": l.industry,
        "variant": l.variant,
        "email_subject": l.email_subject,
        "email_body": l.email_body,
        "revenue_annual": l.revenue_annual,
        "status": l.status,
        "query": l.query,
        "scraped_at": l.scraped_at.isoformat() if l.scraped_at else "",
        "sent_at": l.sent_at.isoformat() if l.sent_at else "",
        "replied": l.replied,
        "bounced": l.bounced,
        "unsubscribed": l.unsubscribed,
        "pain_points": l.pain_points,
    } for l in leads])


@scraper_bp.route('/leads/<int:lead_id>/send', methods=['POST'])
@login_required
def send_scraper_lead(lead_id):
    lead = ScraperLead.query.filter_by(id=lead_id, user_id=current_user.id).first_or_404()

    if not lead.email_found:
        return jsonify({"error": "No email found for this lead"}), 400

    from models import EmailAccount
    from email_service import send_email

    accounts = EmailAccount.query.filter_by(user_id=current_user.id, active=True).all()
    if not accounts:
        return jsonify({"error": "No active email account. Configure one in Settings."}), 400

    class _FakeUser:
        display_name = current_user.display_name
        signature = current_user.signature

    ok, err = send_email(accounts[0], lead.email_found,
                         lead.email_subject, lead.email_body, _FakeUser())

    if ok:
        lead.status = "sent"
        lead.sent_at = datetime.utcnow()
        # Schedule follow-ups
        lead.followup_1_due = (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%d")
        lead.followup_2_due = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")
        db.session.commit()
        return jsonify({"ok": True})
    else:
        lead.status = "failed"
        lead.send_error = err
        db.session.commit()
        return jsonify({"ok": False, "error": err})


@scraper_bp.route('/leads/add-to-pool', methods=['POST'])
@login_required
def add_to_pool():
    data = request.get_json(silent=True) or {}
    lead_ids = data.get("lead_ids", [])

    if not lead_ids:
        lead_ids = [l.id for l in ScraperLead.query.filter_by(
            user_id=current_user.id
        ).filter(ScraperLead.email_found != '').all()]

    added = 0
    skipped = 0
    for lid in lead_ids:
        sl = ScraperLead.query.filter_by(id=int(lid), user_id=current_user.id).first()
        if not sl or not sl.email_found:
            skipped += 1
            continue

        existing = Lead.query.filter_by(user_id=current_user.id, email=sl.email_found).first()
        if existing:
            skipped += 1
            continue

        # Try to parse name
        parts = sl.name.split(" ", 1)
        first = parts[0] if parts else sl.name
        last = parts[1] if len(parts) > 1 else ""

        lead = Lead(
            user_id=current_user.id,
            email=sl.email_found,
            first_name=first,
            last_name=last,
            company=sl.name,
            website=sl.website,
            phone=sl.phone,
            signal_1=", ".join(sl.pain_points[:1]) if sl.pain_points else "",
            signal_2=", ".join(sl.pain_points[1:2]) if len(sl.pain_points) > 1 else "",
            notes=sl.reasoning,
            source=f"scraper:{sl.source}",
        )
        db.session.add(lead)
        added += 1

    db.session.commit()
    return jsonify({"ok": True, "added": added, "skipped": skipped})


@scraper_bp.route('/leads/export/csv')
@login_required
def export_csv():
    leads = ScraperLead.query.filter_by(user_id=current_user.id).order_by(ScraperLead.scraped_at.desc()).all()
    if not leads:
        return jsonify({"error": "No leads to export"}), 400

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name", "address", "phone", "website", "email_found", "email_tier",
                     "score", "industry", "variant", "revenue_annual", "status",
                     "email_subject", "query", "scraped_at", "sent_at", "replied", "bounced", "unsubscribed"])

    for l in leads:
        writer.writerow([l.name, l.address, l.phone, l.website, l.email_found, l.email_tier,
                         l.score, l.industry, l.variant, l.revenue_annual, l.status,
                         l.email_subject, l.query,
                         l.scraped_at.strftime("%Y-%m-%d") if l.scraped_at else "",
                         l.sent_at.strftime("%Y-%m-%d") if l.sent_at else "",
                         l.replied, l.bounced, l.unsubscribed])

    output.seek(0)
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=scraper_leads.csv"})


@scraper_bp.route('/leads/clear', methods=['POST'])
@login_required
def clear_leads():
    ScraperLead.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return jsonify({"ok": True})


@scraper_bp.route('/locations')
@login_required
def get_locations():
    return jsonify(LOCATION_PRESETS)


@scraper_bp.route('/industries')
@login_required
def get_industries():
    return jsonify(ALL_INDUSTRIES)
