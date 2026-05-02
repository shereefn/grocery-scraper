import asyncio
import json
import logging
import re
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

# --- 1. INSERT YOUR GEMINI API KEY HERE ---
import os

# --- CLOUD SECURITY: Pulling keys from hidden environment variables ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL   = os.environ.get("SUPABASE_URL")
SUPABASE_KEY   = os.environ.get("SUPABASE_KEY")

SEARCH_URL    = "https://d4donline.com/en/saudi-arabia/riyadh/products"
CARD_SELECTOR = "a.product-card"

TEST_STORES = ["Danube"] 
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
# Supabase Cloud Database Helpers (With Auto-Cleaning)
# ---------------------------------------------------------------------------

def load_cache() -> Dict[str, str]:
    log.info("☁️  Connecting to Supabase to load memory...")
    try:
        # Ask Supabase for all our saved items
        response = supabase.table("ai_cache").select("*").execute()
        raw_data = response.data
        
        healthy_cache = {}
        bad_urls = []
        
        for row in raw_data:
            url = row["image_url"]
            name = row["product_name"]
            
            if name != "Unknown item":
                healthy_cache[url] = name
            else:
                bad_urls.append(url)
                
        # --- THE CLOUD AUTO-CLEANER ---
        if bad_urls:
            log.info("🧹 Auto-cleaning %d 'Unknown item' entries from Supabase...", len(bad_urls))
            # Tell Supabase to delete all the bad URLs in one quick batch
            supabase.table("ai_cache").delete().in_("image_url", bad_urls).execute()
            
        log.info("✅ Loaded %d healthy items from Cloud Memory.", len(healthy_cache))
        return healthy_cache
        
    except Exception as e:
        log.error("❌ Failed to connect to Supabase: %s", e)
        log.warning("Starting with an empty memory for this run.")
        return {}

def save_to_cloud(image_url: str, product_name: str) -> None:
    """Instantly beams a new product directly to the Supabase database."""
    try:
        # Upsert means "Insert it, but if the URL already exists, just update it"
        supabase.table("ai_cache").upsert({
            "image_url": image_url, 
            "product_name": product_name
        }).execute()
    except Exception as e:
        log.error("Failed to save to Supabase: %s", e)


# ---------------------------------------------------------------------------
# Helpers
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
                log.warning("Google API busy! Retrying image in %d seconds... (Attempt %d/%d)", wait_time, attempt + 1, max_retries)
                await asyncio.sleep(wait_time)
            else:
                log.warning("Gemini AI failed for %s: %s", image_url, e)
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

    log.info("Parsed %d products.", len(results))
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

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
        limits = httpx.Limits(max_connections=10)
        
        async with httpx.AsyncClient(limits=limits, headers=headers) as http_client:
            tasks = [process_with_limit(p, http_client) for p in uncached_products]
            completed = await asyncio.gather(*tasks)
            
            for idx, (p, name) in enumerate(completed):
                p["Product"] = name
                ai_cache[p["Image_URL"]] = name
                log.info("  [%d/%d] Identified: %s", idx + 1, len(uncached_products), name)
                
                # Instantly save the new item directly to Supabase!
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
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="ar-SA",
            timezone_id="Asia/Riyadh"
        )
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )

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
            log.info("Found %d stores.", len(store_links))

            for store in store_links:
                store_name = store["name"] or store["href"]

                if TEST_STORES and not any(
                    t.lower() in store_name.lower() for t in TEST_STORES
                ):
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

    log.info("Stage 1 Deduplication (Image URL based)...")
    unique_results = []
    seen = set()
    for p in all_results:
        base_img_url = p.get('Image_URL', '').split('?')[0]
        fingerprint = f"{base_img_url}|{p.get('Store', '')}"
        
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique_results.append(p)
            
    all_results = unique_results

    all_results = await enrich_product_names(all_results)

    log.info("Stage 2 Deduplication (AI Name + Price + Store based)...")
    final_results = []
    seen_post = set()
    for p in all_results:
        product_name = p.get('Product', '').lower().strip()
        store = p.get('Store', '')
        price = p.get('Price', 0)
        
        post_fingerprint = f"{product_name}|{store}|{price}"
        
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
      <label>Sort By</label>
      <select id="sort-price" onchange="applyFilters()">
        <option value="">Default Order</option>
        <option value="asc">Price: Low to High</option>
        <option value="desc">Price: High to Low</option>
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
      <label>Filter Brands / Stores</label>
      <div class="checkbox-panel" id="store-checkboxes">
      </div>
    </div>

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
    
    const sortVal     = document.getElementById('sort-price').value;
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

    if (sortVal === 'asc') {{
        filteredData.sort((a, b) => (a.Price || 0) - (b.Price || 0));
    }} else if (sortVal === 'desc') {{
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
    document.getElementById('sort-price').value = '';
    document.querySelectorAll('.store-cb').forEach(cb => cb.checked = false);
    slider.value = maxPrice;
    applyFilters();
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
        log.info("Filtered down to %d matched products.", len(results))
    
    if results:
        OUTPUT_JSON.write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        save_html(results)
        log.info("Done. %d products saved.", len(results))
    else:
        log.warning("No results found.")


if __name__ == "__main__":
    asyncio.run(main())
