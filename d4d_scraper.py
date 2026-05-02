import asyncio
import json
import logging
import re
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from random import uniform
from typing import Optional, List, Dict

import httpx
from google import genai
from google.genai import types
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PwTimeout
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL   = os.environ.get("SUPABASE_URL")
SUPABASE_KEY   = os.environ.get("SUPABASE_KEY")
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD") # From GitHub Secrets

# --- EMAIL ALERT SETTINGS ---
SENDER_EMAIL = "itzshereef@gmail.com"
RECEIVER_EMAIL = "shereefneikkan@gmail.com"

# ADD YOUR CUSTOM ALERTS HERE! 
PRICE_ALERTS = [
    {"keyword": "anchor milk powder 2.25", "max_price": 40.0},
    {"keyword": "almarai milk", "max_price": 45.0},
    {"keyword": "nido", "max_price": 60.0}
]

SEARCH_URL    = "https://d4donline.com/en/saudi-arabia/riyadh/products"
CARD_SELECTOR = "a.product-card"

TEST_STORES = ["Othaim Markets", "Mark & Save"] 
TARGET_PRODUCTS = []

OUTPUT_HTML = Path("d4d_results.html")
OUTPUT_JSON = Path("d4d_results.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

client = genai.Client(api_key=GEMINI_API_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------------------------------------------------------------------------
# Email Alert Engine
# ---------------------------------------------------------------------------
def check_alerts_and_send_email(products: List[Dict]):
    if not EMAIL_APP_PASSWORD:
        log.warning("No EMAIL_APP_PASSWORD found in secrets. Skipping email alerts.")
        return

    log.info("Checking products against your Price Alerts...")
    found_deals = []

    for p in products:
        product_name = p.get("Product", "").lower()
        price = p.get("Price")
        store = p.get("Store", "Unknown Store")
        image_url = p.get("Image_URL")
        
        if not price: 
            continue
            
        for alert in PRICE_ALERTS:
            search_tokens = alert["keyword"].lower().split()
            match_search = all(token in product_name for token in search_tokens)
            
            if match_search and price <= alert["max_price"]:
                found_deals.append({
                    "target_price": alert["max_price"],
                    "product_name": p.get("Product"),
                    "store": store,
                    "price": price,
                    # We need the image here to add to the HTML mail
                    "image": image_url 
                })

    if not found_deals:
        log.info("No products matched your target prices today.")
        return

    log.info(f"🚨 FOUND {len(found_deals)} DEALS MATCHING ALERTS! Sending email...")
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚨 Grocery Alert: Found {len(found_deals)} items below your target price!"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL

    # --- HTML Email Body (Redesigned with Website Style Cards) ---
    html_body = f"""
    <html>
    <head>
        <style>
            .container {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; background-color: #f4f6f8; padding: 20px; }}
            .card {{ background-color: #ffffff; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border: 1px solid #e1e4e8; }}
            .card-img-link {{ text-decoration: none; display: block; text-align: center; margin-bottom: 15px; }}
            .card-img {{ width: 150px; height: 150px; object-fit: contain; border-radius: 8px; border: 1px solid #f1f3f4; background-color: white; }}
            .card-details {{ text-align: left; }}
            .card-title {{ color: #1a73e8; font-size: 18px; font-weight: 600; text-decoration: none; margin-bottom: 8px; display: block; }}
            .card-store {{ color: #5f6368; font-size: 14px; margin-bottom: 8px; }}
            .card-price-container {{ font-size: 16px; margin-top: 10px; }}
            .card-price {{ color: #188038; font-weight: bold; font-size: 20px; }}
            .target-price {{ color: #5f6368; font-size: 13px; font-style: italic; margin-left: 5px; }}
            .website-btn {{ display: inline-block; padding: 12px 24px; background-color: #0066cc; color: white; text-decoration: none; border-radius: 8px; font-weight: bold; margin-top: 20px; }}
        </style>
    </head>
    <body class="container">
        <h2>Your Deal Alerts for Today:</h2>
        <hr style="border: 0; border-top: 1px solid #ddd; margin-bottom: 20px;">
    """

    for deal in found_deals:
        # Wrap image and title in a link that points to the full-size image to "enlarge" it
        product_url_enlarge = deal['image']
        safe_name = deal['product_name'].replace('"', '&quot;')

        html_body += f"""
        <!-- Website Style Deal Card -->
        <div class="card">
            <a href="{product_url_enlarge}" class="card-img-link" title="Click to view full image">
                <img src="{deal['image']}" alt="{safe_name}" class="card-img">
            </a>
            <div class="card-details">
                <a href="{product_url_enlarge}" class="card-title" title="Click to view full image">{deal['product_name']}</a>
                <p class="card-store"><strong>Store:</strong> {deal['store']}</p>
                <div class="card-price-container">
                    <span class="card-price">SAR {deal['price']}</span>
                    <span class="target-price">(Target was <= {deal['target_price']})</span>
                </div>
            </div>
        </div>
        """
    
    html_body += f'''
        <div style="text-align: center;">
            <a href="https://shereefn.github.io/grocery-scraper/d4d_results.html" class="website-btn">View All Deals on Website</a>
        </div>
    </body>
    </html>
    '''

    msg.attach(MIMEText(html_body, "html"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SENDER_EMAIL, EMAIL_APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        log.info("✅ Alert email sent successfully!")
    except Exception as e:
        log.error(f"❌ Failed to send email: {e}")


# ---------------------------------------------------------------------------
# Supabase Cloud Database Helpers
# ---------------------------------------------------------------------------

def load_cache() -> Dict[str, str]:
    log.info("☁️  Connecting to Supabase to load memory...")
    try:
        healthy_cache = {}
        bad_urls = []
        
        offset = 0
        limit = 1000
        
        while True:
            response = supabase.table("ai_cache").select("*").range(offset, offset + limit - 1).execute()
            raw_data = response.data
            
            if not raw_data:
                break
                
            for row in raw_data:
                url = row["image_url"]
                name = row["product_name"]
                
                if name != "Unknown item":
                    healthy_cache[url] = name
                else:
                    bad_urls.append(url)
            
            if len(raw_data) < limit:
                break
                
            offset += limit
            
        if bad_urls:
            log.info("🧹 Auto-cleaning %d 'Unknown item' entries from Supabase...", len(bad_urls))
            supabase.table("ai_cache").delete().in_("image_url", bad_urls).execute()
            
        log.info("✅ Loaded %d healthy items from Cloud Memory.", len(healthy_cache))
        return healthy_cache
        
    except Exception as e:
        log.error("❌ Failed to connect to Supabase: %s", e)
        return {}

def save_to_cloud(image_url: str, product_name: str) -> None:
    try:
        supabase.table("ai_cache").upsert({
            "image_url": image_url, 
            "product_name": product_name
        }).execute()
    except Exception as e:
        log.error("Failed to save to Supabase: %s", e)


# ---------------------------------------------------------------------------
# AI and Parsing Helpers
# ---------------------------------------------------------------------------

def clean_price(raw: str) -> Optional[float]:
    raw = re.sub(r"⚠.*", "", raw, flags=re.DOTALL).strip()
    matches = re.findall(r"\d+(?:\.\d+)?", raw.replace(",", ""))
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None

def extract_price(price_elem) -> Optional[float]:
    if not price_elem:
        return None
    return clean_price(price_elem.get_text(" ", strip=True))


async def read_product_name_from_image(image_url: str, http_client: httpx.AsyncClient) -> str:
    if not image_url:
        return "Unknown item"
        
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = await http_client.get(image_url, timeout=15)
            if resp.status_code != 200:
                return "Unknown item"

            prompt = "You are a data extractor. Look at this grocery product image. Extract the Brand Name, Product Name, and Weight/Volume in English. Output ONLY the final product string on a single line. Ignore Arabic. Do not add markdown, quotes, or conversational text."

            response = await client.aio.models.generate_content(
                model='gemini-2.5-flash-lite',
                contents=[
                    types.Part.from_bytes(data=resp.content, mime_type='image/jpeg'),
                    prompt
                ]
            )
            return response.text.strip().replace('\n', ' ')

        except Exception as e:
            error_message = str(e)
            if "503" in error_message or "429" in error_message:
                wait_time = (attempt + 1) * 5 
                log.warning("Google API busy! Retrying... (Attempt %d/%d)", attempt + 1, max_retries)
                await asyncio.sleep(wait_time)
            else:
                break 

    return "Unknown item"


def parse_products(html: str) -> List[Dict]:
    soup  = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("a", class_="product-card")

    results: List[Dict] = []
    for card in cards:
        price_elem = card.find("div", class_="price-wrapper")
        store_elem = card.find("h2",  class_="product-description")
        offer_elem = card.find("div", class_="offer_tag")

        store_name = store_elem.get_text(strip=True) if store_elem else "Unknown store"
        image_url  = card.get("data-image-tr", "").strip()
        price      = extract_price(price_elem)
        offer      = offer_elem.get_text(strip=True).replace('"', '') if offer_elem else ""

        results.append({
            "Store":     store_name,
            "Product":   "",
            "Price":     price,
            "Offer":     offer,
            "Image_URL": image_url,
        })
    return results


async def enrich_product_names(products: List[Dict]) -> List[Dict]:
    ai_cache = load_cache()

    uncached_products = []
    for p in products:
        img_url = p["Image_URL"]
        if img_url in ai_cache:
            p["Product"] = ai_cache[img_url]
        elif img_url:
            uncached_products.append(p)

    if uncached_products:
        log.info("Running Gemini AI for %d NEW images...", len(uncached_products))
        semaphore = asyncio.Semaphore(3)

        async def process_with_limit(product, client_instance):
            async with semaphore:
                name = await read_product_name_from_image(product["Image_URL"], client_instance)
                return product, name

        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        limits = httpx.Limits(max_connections=10)
        
        async with httpx.AsyncClient(limits=limits, headers=headers) as http_client:
            tasks = [process_with_limit(p, http_client) for p in uncached_products]
            completed = await asyncio.gather(*tasks)
            
            for idx, (p, name) in enumerate(completed):
                p["Product"] = name
                ai_cache[p["Image_URL"]] = name
                save_to_cloud(p["Image_URL"], name)
                
    else:
        log.info("All products were found in the Cloud Memory! Skipped AI processing.")

    return products


# ---------------------------------------------------------------------------
# Playwright scraping
# ---------------------------------------------------------------------------

async def scrape(url: str) -> List[Dict]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="ar-SA",
            timezone_id="Asia/Riyadh"
        )
        await context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

        page        = await context.new_page()
        all_results = []

        try:
            log.info("Loading store list from %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_selector("div#outlet-nav", timeout=20_000)

            store_links = await page.eval_on_selector_all(
                "a.disable_link.company-product",
                "els => els.map(e => ({ name: e.getAttribute('title'), href: e.getAttribute('href') }))"
            )

            for store in store_links:
                store_name = store["name"] or store["href"]

                if TEST_STORES and not any(t.lower() in store_name.lower() for t in TEST_STORES):
                    continue

                store_url = "https://d4donline.com/en/saudi-arabia/riyadh/" + store["href"].lstrip("/")
                log.info("Scraping store: %s", store_name)
                await page.goto(store_url, wait_until="domcontentloaded", timeout=30_000)

                try:
                    await page.wait_for_selector(CARD_SELECTOR, timeout=15_000)
                except PwTimeout:
                    continue

                click_count = 0
                max_clicks = 100 

                while click_count < max_clicks:
                    try:
                        btn = await page.wait_for_selector("a.view-more-products", timeout=5_000)
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        click_count += 1
                        await asyncio.sleep(uniform(1.5, 2.5))
                    except PwTimeout:
                        break

                html     = await page.content()
                products = parse_products(html)
                log.info("  → %d products from %s", len(products), store_name)
                all_results.extend(products)
                await asyncio.sleep(uniform(1.0, 2.0))

        except PwTimeout:
            log.error("Timed out. Check selectors or network.")
            return []
        finally:
            await context.close()
            await browser.close()

    unique_results = []
    seen = set()
    for p in all_results:
        base_img_url = p.get('Image_URL', '').split('?')[0]
        fingerprint = f"{base_img_url}|{p.get('Store', '')}"
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique_results.append(p)
            
    all_results = await enrich_product_names(unique_results)

    final_results = []
    seen_post = set()
    for p in all_results:
        post_fingerprint = f"{p.get('Product', '').lower()}|{p.get('Store', '')}|{p.get('Price', 0)}"
        if post_fingerprint not in seen_post:
            seen_post.add(post_fingerprint)
            final_results.append(p)

    return final_results


# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------

def save_html(data: List[Dict]) -> None:
    products_json = json.dumps(data, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>My Deals | Riyadh</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; background: #f5f7fa; color: #333; overflow-x: hidden; }}
  .navbar {{ display: flex; align-items: center; gap: 16px; background: #ffffff; padding: 16px 24px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); position: sticky; top: 0; z-index: 100; }}
  .hamburger {{ background: none; border: none; font-size: 26px; cursor: pointer; color: #5f6368; display: flex; align-items: center; justify-content: center; padding: 4px 8px; border-radius: 8px; transition: background 0.2s; }}
  .hamburger:hover {{ background: #f1f3f4; color: #202124; }}
  h1 {{ color: #202124; font-size: 22px; font-weight: 600; letter-spacing: -0.5px; }}
  .sidebar {{ position: fixed; top: 0; left: -340px; width: 340px; height: 100%; background: #ffffff; box-shadow: 4px 0 16px rgba(0,0,0,0.1); transition: left 0.3s cubic-bezier(0.4, 0, 0.2, 1); z-index: 1001; display: flex; flex-direction: column; overflow-y: auto; }}
  .sidebar.open {{ left: 0; }}
  .sidebar-overlay {{ position: fixed; inset: 0; background: rgba(0,0,0,0.4); backdrop-filter: blur(2px); z-index: 1000; opacity: 0; pointer-events: none; transition: opacity 0.3s ease; }}
  .sidebar-overlay.active {{ opacity: 1; pointer-events: auto; }}
  .sidebar-header {{ display: flex; justify-content: space-between; align-items: center; padding: 20px 24px; border-bottom: 1px solid #f1f3f4; }}
  .sidebar-header h2 {{ font-size: 18px; font-weight: 600; color: #202124; }}
  .close-btn {{ background: none; border: none; font-size: 28px; cursor: pointer; color: #5f6368; line-height: 1; padding: 0 8px; }}
  .close-btn:hover {{ color: #202124; }}
  .sidebar-content {{ padding: 24px; display: flex; flex-direction: column; gap: 24px; }}
  .filter-group {{ display: flex; flex-direction: column; gap: 8px; }}
  .filter-group label {{ font-size: 13px; color: #5f6368; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
  select, input[type=text] {{ padding: 12px 14px; border: 1px solid #dadce0; border-radius: 8px; font-size: 14px; outline: none; background: #ffffff; width: 100%; transition: border-color 0.2s; }}
  select:focus, input[type=text]:focus {{ border-color: #1a73e8; }}
  .checkbox-panel {{ border: 1px solid #dadce0; border-radius: 8px; padding: 16px; background: #fafafa; max-height: 200px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }}
  .checkbox-label {{ display: flex; align-items: center; gap: 10px; font-size: 14px; color: #3c4043; cursor: pointer; }}
  .checkbox-label input {{ cursor: pointer; width: 18px; height: 18px; accent-color: #1a73e8; }}
  .slider-container {{ display: flex; align-items: center; gap: 12px; }}
  input[type=range] {{ flex: 1; accent-color: #1a73e8; cursor: pointer; }}
  #price-range-label {{ font-size: 14px; color: #1a73e8; font-weight: 700; min-width: 80px; text-align: right; }}
  .btn-reset {{ padding: 12px; background: #f1f3f4; color: #202124; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: background 0.2s; margin-top: auto; }}
  .btn-reset:hover {{ background: #e8eaed; }}
  .main-wrapper {{ padding: 24px; max-width: 1400px; margin: 0 auto; }}
  .meta-bar {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; font-size: 14px; color: #5f6368; }}
  .table-wrap {{ border-radius: 12px; overflow-x: auto; box-shadow: 0 1px 3px rgba(0,0,0,0.1); background: white; border: 1px solid #dadce0; }}
  table {{ width: 100%; border-collapse: collapse; min-width: 650px; }}
  th {{ background: #f8f9fa; color: #5f6368; padding: 14px 16px; text-align: left; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #dadce0; }}
  td {{ padding: 16px; border-bottom: 1px solid #f1f3f4; vertical-align: middle; }}
  tr:hover td {{ background: #f8f9fa; }}
  td:first-child {{ width: 100px; padding: 10px; }}
  td:nth-child(2) {{ font-size: 15px; color: #202124; font-weight: 500; line-height: 1.4; }}
  td:nth-child(3) {{ color: #5f6368; font-size: 14px; width: 150px; }}
  td:nth-child(4) {{ color: #188038; font-weight: 700; font-size: 16px; width: 120px; }}
  td:nth-child(5) {{ width: 130px; }}
  .badge-offer {{ background: #fce8e6; color: #c5221f; padding: 6px 10px; border-radius: 6px; font-size: 12px; font-weight: 700; white-space: nowrap; display: inline-block; }}
  img {{ width: 80px; height: 80px; object-fit: contain; border-radius: 8px; cursor: pointer; transition: transform 0.2s; border: 1px solid #f1f3f4; background: white; display: block; }}
  img:hover {{ transform: scale(1.1); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
  .loading-indicator {{ text-align: center; padding: 20px; color: #5f6368; font-size: 14px; font-weight: 500; }}
  
  /* THEATER MODE POPUP */
  #popup-overlay {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.92); z-index: 2000; align-items: center; justify-content: center; padding: 20px; backdrop-filter: blur(5px); flex-direction: column; }}
  #popup-overlay.active {{ display: flex; }}
  #popup-box {{ background: white; border-radius: 16px; padding: 0; width: 90vw; max-width: 500px; aspect-ratio: 1 / 1; position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; overflow: hidden; box-shadow: 0 10px 40px rgba(0,0,0,0.5); }}
  
  #popup-img {{ width: 100%; height: 100%; object-fit: contain; cursor: zoom-in; transition: transform 0.3s cubic-bezier(0.25, 1, 0.5, 1); }}
  #popup-img.zoomed {{ transform: scale(1.8); cursor: zoom-out; }}
  
  #popup-title {{ display: none; }}
  
  #popup-close {{ position: absolute; top: 12px; right: 12px; background: #ef4444; color: white; width: 36px; height: 36px; border-radius: 50%; font-size: 20px; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s; z-index: 2002; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }}
  #popup-close:hover {{ background: #dc2626; transform: scale(1.1); }}
</style>
</head>
<body>

<div class="navbar">
  <button class="hamburger" onclick="toggleSidebar()">&#9776;</button>
  <h1>My Deals</h1>

      <div class="filter-group">
      <label>Search</label>
      <input type="text" id="filter-product" placeholder="e.g. almarai milk powder" oninput="applyFilters()">
    </div>
    
</div>

<div class="sidebar-overlay" id="sidebarOverlay" onclick="toggleSidebar()"></div>

<div class="sidebar" id="filterSidebar">
  <div class="sidebar-header">
    <h2>Filters & Sorting</h2>
    <button class="close-btn" onclick="toggleSidebar()">&times;</button>
  </div>
  
  <div class="sidebar-content">
    
<div class="filter-group">
                <label>SORT BY</label>
                <select id="sortDropdown" onchange="applyFilters()">
                    <option value="default">Default Order</option>
                    <option value="price-asc" selected>Price: Low to High</option>
                    <option value="price-desc">Price: High to Low</option>
                </select>
            </div>

    <div class="filter-group">
      <label>Max Price</label>
      <div class="slider-container">
        <input type="range" id="filter-price" min="0" max="10000" value="10000" step="5" oninput="applyFilters()">
        <span id="price-range-label">SAR 10000</span>
      </div>
    </div>
    
<div class="filter-group">
                <label>FILTER BRANDS / STORES</label>
                <input type="text" id="storeSearchInput" class="store-search-box" placeholder="Find a store..." onkeyup="filterStoreList()">
                
                <div class="checkbox-panel" id="store-checkboxes">
                    <!-- Javascript auto-fills checkboxes here based on your data -->
                </div>
            </div>
            
    <button class="filter-btn" onclick="toggleSidebar()">Apply Filters</button>
    <button class="btn-reset" onclick="resetFilters()">Clear All Filters</button>
  </div>
</div>

<div class="main-wrapper">
  <div class="meta-bar">
    <span id="count">Loading products...</span>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Image</th><th>Product Name</th><th>Store</th><th>Price</th><th>Offer</th></tr>
      </thead>
      <tbody id="tbody">
      </tbody>
    </table>
    <div id="sentinel" class="loading-indicator">Scroll down for more deals...</div>
  </div>
</div>

<div id="popup-overlay" onclick="closePopup(event)">
  <div id="popup-box">
    <button id="popup-close" onclick="closePopup(event)">&#10005;</button>
    <img id="popup-img" src="" alt="" onclick="toggleZoom(event)">
    <div id="popup-title"></div>
  </div>
</div>

<script>
  const rawData = {products_json}; 
  let filteredData = [];
  let currentIndex = 0;
  const CHUNK_SIZE = 30;

  const tbody = document.getElementById('tbody');
  const sentinel = document.getElementById('sentinel');
  const countLabel = document.getElementById('count');

  const stores = [...new Set(rawData.map(r => r.Store))].sort();
  const cbContainer = document.getElementById('store-checkboxes');
  stores.forEach(s => {{
    const lbl = document.createElement('label');
    lbl.className = 'checkbox-label';
    lbl.innerHTML = `<input type="checkbox" value="${{s}}" class="store-cb" onchange="applyFilters()"> ${{s}}`;
    cbContainer.appendChild(lbl);
  }});

  const prices = rawData.map(r => r.Price).filter(p => p > 0);
  const maxPrice = prices.length ? Math.ceil(Math.max(...prices) / 10) * 10 : 100;
  const slider = document.getElementById('filter-price');
  slider.max   = maxPrice;
  slider.value = maxPrice;
  document.getElementById('price-range-label').textContent = 'SAR ' + maxPrice;

  const sidebar = document.getElementById('filterSidebar');
  const overlay = document.getElementById('sidebarOverlay');
  function toggleSidebar() {{
    sidebar.classList.toggle('open');
    overlay.classList.toggle('active');
  }}

  function applyFilters() {{
    const searchQuery = document.getElementById('filter-product').value.toLowerCase().trim();
    const searchTokens = searchQuery.split(/\s+/).filter(token => token.length > 0);
    
    const sortVal     = document.getElementById('sortDropdown').value;
    const max         = parseFloat(slider.value);
    
    const checkedBoxes = Array.from(document.querySelectorAll('.store-cb:checked'));
    const selectedStores = checkedBoxes.map(cb => cb.value);

    document.getElementById('price-range-label').textContent = 'SAR ' + max;

    filteredData = rawData.filter(item => {{
      const productName = (item.Product || "Unknown item").toLowerCase();
      
      let matchSearch = true;
      if (searchTokens.length > 0) {{
          matchSearch = searchTokens.every(token => productName.includes(token));
      }}

      const matchStore  = selectedStores.length === 0 || selectedStores.includes(item.Store);
      const matchPrice  = (item.Price === null) || (item.Price <= max);
      
      return matchSearch && matchStore && matchPrice;
    }});

    if (sortVal === 'price-asc') {{
        filteredData.sort((a, b) => (a.Price || 0) - (b.Price || 0));
    }} else if (sortVal === 'price-desc') {{
        filteredData.sort((a, b) => (b.Price || 0) - (a.Price || 0));
    }}

    currentIndex = 0;
    tbody.innerHTML = ''; 
    
    loadMore();
  }}

  function loadMore() {{
    if (currentIndex >= filteredData.length) {{
        sentinel.style.display = 'none';
        return;
    }}
    sentinel.style.display = 'block';

    const chunk = filteredData.slice(currentIndex, currentIndex + CHUNK_SIZE);
    const fragment = document.createDocumentFragment();

    chunk.forEach(item => {{
      const tr = document.createElement('tr');
      const safeName = (item.Product || "Unknown item").replace(/'/g, "&apos;").replace(/"/g, "&quot;");
      const priceStr = item.Price ? `SAR ${{item.Price}}` : "—";
      const offerStr = item.Offer ? `<span class="badge-offer">${{item.Offer}}</span>` : "—";
      const imgTag = item.Image_URL 
          ? `<img src="${{item.Image_URL}}" alt="${{safeName}}" loading="lazy" onclick="openPopup('${{item.Image_URL}}', '${{safeName}}')">` 
          : "No image";

      tr.innerHTML = `
          <td>${{imgTag}}</td>
          <td>${{item.Product || "Unknown item"}}</td>
          <td>${{item.Store || "Unknown store"}}</td>
          <td>${{priceStr}}</td>
          <td>${{offerStr}}</td>
      `;
      fragment.appendChild(tr);
    }});

    tbody.appendChild(fragment);
    currentIndex += chunk.length;
    
    countLabel.innerHTML = `Showing <strong>${{currentIndex}}</strong> of <strong>${{filteredData.length}}</strong> products`;
  }}

  const observer = new IntersectionObserver((entries) => {{
    if (entries[0].isIntersecting) {{
        loadMore();
    }}
  }}, {{ rootMargin: "200px" }}); 
  
  observer.observe(sentinel);

  applyFilters();

  function resetFilters() {{
    document.getElementById('filter-product').value = '';
    document.getElementById('sortDropdown').value = 'price-asc';
    document.getElementById('storeSearchInput').value = '';
    document.querySelectorAll('.store-cb').forEach(cb => cb.checked = false);
    slider.value = maxPrice;
    filterStoreList();
    applyFilters();
  }}

  function filterStoreList() {{
      let input = document.getElementById('storeSearchInput').value.toLowerCase();
      let storeLabels = document.querySelectorAll('.checkbox-label');
      
      storeLabels.forEach(label => {{
          let storeName = label.innerText.toLowerCase();
          if (storeName.includes(input)) {{
              label.style.display = "flex";
          }} else {{
              label.style.display = "none";
          }}
      }});
  }}

  function openPopup(src, title) {{
    const img = document.getElementById('popup-img');
    img.src = src;
    img.classList.remove('zoomed'); 
    
    document.getElementById('popup-title').innerHTML = title;
    
    document.getElementById('popup-overlay').classList.add('active');
  }}

  function toggleZoom(e) {{
    e.stopPropagation(); 
    const img = document.getElementById('popup-img');
    img.classList.toggle('zoomed');
  }}

  function closePopup(e) {{
    if (e && e.target && e.target.id === 'popup-img') return;
    
    if (!e || e.target === document.getElementById('popup-overlay') || e.currentTarget === document.getElementById('popup-close')) {{
      document.getElementById('popup-overlay').classList.remove('active');
    }}
  }}

  document.addEventListener('keydown', e => {{
    if (e.key === 'Escape') {{
      document.getElementById('popup-overlay').classList.remove('active');
    }}
  }});
</script>
</body>
</html>"""

    OUTPUT_HTML.write_text(html, encoding="utf-8")
    log.info("Saved HTML → %s", OUTPUT_HTML)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    results = await scrape(SEARCH_URL)
    
    if TARGET_PRODUCTS and results:
        log.info("Filtering results to only include items from the TARGET_PRODUCTS list...")
        filtered_results = []
        for item in results:
            product_name = item.get("Product", "").lower()
            if any(target.lower() in product_name for target in TARGET_PRODUCTS):
                filtered_results.append(item)
                
        results = filtered_results
        
    if results:
        OUTPUT_JSON.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        
        # Check alerts and send the styled email
        check_alerts_and_send_email(results)
        
        save_html(results)
        log.info("Done. %d products saved.", len(results))
    else:
        log.warning("No results found.")


if __name__ == "__main__":
    asyncio.run(main())
