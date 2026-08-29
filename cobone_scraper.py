import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TARGET_URL = "https://www.cobone.com/en/deals/food-dining-riyadh?srsltid=AfmBOorhxHFDXHVmx_Pg9F4rvaXmw9DuBhhAN4QhT1O1eDqjvQ5pBnQS"
OUTPUT_HTML = Path("cobone_results.html")
OUTPUT_JSON = Path("cobone_results.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

async def scrape_cobone(url: str) -> List[Dict]:
    async with async_playwright() as pw:
        # STEALTH MODE
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="en-US"
        )
        page = await context.new_page()
        log.info("🔍 Loading Cobone Riyadh Food Deals...")
        
        try:
            await page.goto(url, wait_until="commit", timeout=90_000)
            
            # Scroll to load all dynamic deal cards
            for i in range(8):
                await page.mouse.wheel(0, 1500)
                await asyncio.sleep(1.5)
                
            html = await page.content()
            log.info("✅ Successfully grabbed website HTML.")
        except Exception as e:
            log.error(f"❌ Failed to load page: {e}")
            html = ""
            
        await browser.close()
        
    soup = BeautifulSoup(html, "html.parser")
    all_results = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Target the exact links wrapping the deal cards
    deals = soup.select("a[href*='/deals/']")
    log.info(f"🔎 Found {len(deals)} potential deal links. Extracting precise data...")
    
    seen_urls = set()
    
    for card in deals:
        href = card.get('href', '')
        if "categories" in href.lower() or "/ar/" in href.lower(): continue
        
        deal_link = "https://www.cobone.com" + href if href.startswith('/') else href
        if deal_link in seen_urls: continue
        
        # 1. Target exactly the <span class="title">
        title_tag = card.select_one(".title")
        if not title_tag: continue  
        title = title_tag.get_text(strip=True)
        
        # 2. Target exactly the <span class="new"> for the discounted price
        price_tag = card.select_one("span.new")
        if not price_tag: continue
        price_str = price_tag.get_text(strip=True)
        try:
            price = float(re.sub(r'[^\d.]', '', price_str))
        except ValueError:
            continue
            
        # 3. Target exactly the <span class="old"> for the original price
        old_price = None
        old_price_tag = card.select_one("span.old")
        if old_price_tag:
            try:
                old_price = float(re.sub(r'[^\d.]', '', old_price_tag.get_text(strip=True)))
            except ValueError:
                pass
            
        # 4. Target the <span class="discount"> box
        offer = ""
        discount_tag = card.select_one(".discount")
        if discount_tag:
            offer_match = re.search(r'(\d+)', discount_tag.get_text(strip=True))
            if offer_match:
                offer = f"{offer_match.group(1)}% Off"
                
        # 5. Target the Location/Store
        store_name = "Cobone Deal"
        loc_tag = card.select_one(".locations-sold-flex")
        if loc_tag:
            loc_text = loc_tag.get_text(" ", strip=True)
            store_name = re.sub(r'\d+\s*Sold', '', loc_text, flags=re.IGNORECASE).strip()
            
        # 6. Extract the Image URL (SMART LAZY-LOAD FIX WITH 'data-lazy')
        img = card.select_one("img")
        image_url = ""
        if img:
            # We added 'data-lazy' to the very front of the list!
            for attr in ["data-lazy", "data-src", "data-original", "src"]:
                url = img.get(attr, "")
                if url and "base64" not in url:
                    image_url = url
                    break
        
        # Fix CDN links that are missing the protocol
        if image_url.startswith("//"):
            image_url = "https:" + image_url
        elif image_url.startswith("/"):
            image_url = "https://www.cobone.com" + image_url
            
        all_results.append({
            "Store": store_name,
            "Product": title,
            "Price": price,
            "Old_Price": old_price,
            "Offer": offer,
            "Image_URL": image_url,
            "Deal_URL": deal_link,
            "Fetched_Date": today_str
        })
        seen_urls.add(deal_link)
        
    return all_results

def save_html(data: List[Dict]) -> None:
    products_json = json.dumps(data, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>My Deals | Food Offers</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; background: #f5f7fa; color: #333; overflow-x: hidden; }}
  
  /* NAVBAR & HERO SEARCH BAR UI */
  .navbar {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; background: #ffffff; padding: 16px 24px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); position: sticky; top: 0; z-index: 100; flex-wrap: wrap; }}
  .nav-left {{ display: flex; align-items: center; gap: 16px; justify-content: flex-start; }}
  .nav-center {{ flex: 1; display: flex; justify-content: center; padding: 0 20px; min-width: 300px; }}
  .nav-right {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  
  .hamburger {{ background: none; border: none; font-size: 26px; cursor: pointer; color: #5f6368; display: flex; align-items: center; justify-content: center; padding: 4px 8px; border-radius: 8px; transition: background 0.2s; }}
  .hamburger:hover {{ background: #f1f3f4; color: #202124; }}
  h1 {{ color: #202124; font-size: 22px; font-weight: 600; letter-spacing: -0.5px; white-space: nowrap; margin: 0; }}
  
  .search-container {{ width: 100%; max-width: 700px; position: relative; }}
  .search-container input {{ width: 100%; padding: 16px 24px 16px 48px; border: 2px solid #e1e4e8; border-radius: 40px; font-size: 16px; font-weight: 500; outline: none; transition: all 0.3s ease; box-shadow: 0 4px 12px rgba(0,0,0,0.05); background: #f8f9fa; }}
  .search-container input:focus {{ border-color: #1a73e8; box-shadow: 0 6px 16px rgba(26, 115, 232, 0.15); background: #ffffff; }}
  .search-container::before {{ content: '🔍'; position: absolute; left: 18px; top: 50%; transform: translateY(-50%); font-size: 18px; color: #5f6368; pointer-events: none; }}
  
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
  select, input[type=text]:not(#filter-product) {{ padding: 12px 14px; border: 1px solid #dadce0; border-radius: 8px; font-size: 14px; outline: none; background: #ffffff; width: 100%; transition: border-color 0.2s; }}
  select:focus, input[type=text]:focus {{ border-color: #1a73e8; }}
  .checkbox-panel {{ border: 1px solid #dadce0; border-radius: 8px; padding: 16px; background: #fafafa; max-height: 200px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }}
  .checkbox-label {{ display: flex; align-items: center; gap: 10px; font-size: 14px; color: #3c4043; cursor: pointer; }}
  .checkbox-label input {{ cursor: pointer; width: 18px; height: 18px; accent-color: #1a73e8; }}
  .slider-container {{ display: flex; align-items: center; gap: 12px; }}
  input[type=range] {{ flex: 1; accent-color: #1a73e8; cursor: pointer; }}
  #price-range-label {{ font-size: 14px; color: #1a73e8; font-weight: 700; min-width: 80px; text-align: right; }}
  .btn-reset {{ padding: 12px; background: #f1f3f4; color: #202124; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: background 0.2s; margin-top: auto; }}
  .btn-reset:hover {{ background: #e8eaed; }}
  
  .main-wrapper {{ padding: 24px; max-width: 1600px; margin: 0 auto; }}
  .meta-bar {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; font-size: 14px; color: #5f6368; }}
  
  /* RESPONSIVE GRID LAYOUT */
  .deal-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
  
  @media (min-width: 768px) {{
    .deal-grid {{ grid-template-columns: repeat(3, 1fr); gap: 16px; }}
  }}
  
  @media (min-width: 1024px) {{
    .deal-grid {{ grid-template-columns: repeat(5, 1fr); gap: 20px; }}
  }}
  
/* OPTIMIZED MOBILE CARD PADDING */
  .card { background: #ffffff; border-radius: 12px; padding: 10px; border: 1px solid #dadce0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; flex-direction: column; gap: 6px; transition: transform 0.2s ease, box-shadow 0.2s ease; position: relative; }
  @media (min-width: 768px) { .card { padding: 16px; gap: 8px; } }
  .card:hover { transform: translateY(-3px); box-shadow: 0 6px 16px rgba(0,0,0,0.1); }
  
  .card-img-wrapper { height: 130px; display: flex; align-items: center; justify-content: center; margin-bottom: 4px; padding: 4px; border-radius: 8px; }
  @media (min-width: 768px) { .card-img-wrapper { height: 180px; margin-bottom: 8px; } }
  .card-img-wrapper img { max-height: 100%; max-width: 100%; object-fit: contain; cursor: pointer; transition: transform 0.2s; }
  .card-img-wrapper img:hover { transform: scale(1.05); }
  
  .title-link { text-decoration: none; color: inherit; display: block; margin-bottom: 2px; outline: none; }
  .title-link:hover .card-title { color: #1a73e8; text-decoration: underline; }
  
  .card-title { font-size: 13px; font-weight: 600; color: #202124; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; text-overflow: ellipsis; min-height: 36px; transition: color 0.2s ease; }
  @media (min-width: 768px) { .card-title { font-size: 15px; min-height: 42px; } }
  
  /* CLEAN PRICE STYLING (MOBILE OPTIMIZED) */
  .card-price-row { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-top: auto; margin-bottom: 4px; }
  .price-badge { color: #202124; display: inline-flex; align-items: center; font-weight: 800; }
  
  /* Scaled down main price for mobile */
  .card-price { font-size: 16px; line-height: 1; }
  @media (min-width: 768px) { .card-price { font-size: 20px; } }
  
  /* UNICODE RIYAL SYMBOL (WINDOWS FIX) */
  .currency-icon { font-size: 1.1em; font-weight: normal; margin-right: 4px; display: inline-block; font-family: "Tahoma", "Arial", sans-serif; }
  .currency-icon-small { font-size: 0.9em; font-weight: normal; margin-right: 3px; display: inline-block; font-family: "Tahoma", "Arial", sans-serif; }
  
  /* Scaled down old price */
  .card-old-price { color: #888888; text-decoration: line-through; font-size: 11px; font-weight: 600; }
  
  /* Removed 'margin-left: auto' so it stacks neatly on mobile if it wraps */
  .badge-offer { background: #00a859; color: #ffffff; padding: 3px 5px; border-radius: 4px; font-size: 10px; font-weight: 800; white-space: nowrap; display: inline-block; letter-spacing: 0.3px; }
  @media (min-width: 768px) { .badge-offer { padding: 4px 8px; font-size: 12px; margin-left: auto; } }
  
  /* STORE BADGE - Added text truncation so long store names don't break the card */
  .card-store { font-size: 11px; color: #1a73e8; background: #e8f0fe; padding: 4px 8px; border-radius: 20px; font-weight: 700; display: inline-block; width: fit-content; max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; letter-spacing: 0.3px; border: 1px solid #d2e3fc; }
  @media (min-width: 768px) { .card-store { font-size: 12px; padding: 4px 12px; } }
  
  .card-date { font-size: 11px; color: #80868b; font-weight: 400; margin-top: 2px; }
  @media (min-width: 768px) { .card-date { font-size: 12px; } }
  
  .loading-indicator {{ text-align: center; padding: 20px; color: #5f6368; font-size: 14px; font-weight: 500; grid-column: 1 / -1; }}
  
  /* THEATER MODE POPUP */
  #popup-overlay {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.92); z-index: 2000; align-items: center; justify-content: center; padding: 20px; backdrop-filter: blur(5px); flex-direction: column; }}
  #popup-overlay.active {{ display: flex; }}
  #popup-box {{ background: white; border-radius: 16px; padding: 0; width: 90vw; max-width: 500px; aspect-ratio: 1 / 1; position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; overflow: hidden; box-shadow: 0 10px 40px rgba(0,0,0,0.5); }}
  #popup-img {{ width: 100%; height: 100%; object-fit: contain; cursor: zoom-in; transition: transform 0.3s cubic-bezier(0.25, 1, 0.5, 1); }}
  #popup-img.zoomed {{ transform: scale(1.8); cursor: zoom-out; }}
  #popup-title {{ display: none; }}
  #popup-close {{ position: absolute; top: 12px; right: 12px; background: #ef4444; color: white; width: 36px; height: 36px; border-radius: 50%; font-size: 20px; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; transition: all 0.2s; z-index: 2002; box-shadow: 0 2px 8px rgba(0,0,0,0.3); }}
  #popup-close:hover {{ background: #dc2626; transform: scale(1.1); }}

  @media (max-width: 768px) {{
    .navbar {{ flex-direction: column; gap: 12px; padding: 12px; align-items: stretch; }}
    .nav-left {{ width: 100%; justify-content: flex-start; gap: 12px; }}
    .nav-center {{ width: 100%; padding: 0; min-width: auto; }}
    .nav-right {{ width: 100%; justify-content: center; }}
  }}
</style>
</head>
<body>

<div class="navbar">
  <div class="nav-left">
    <button class="hamburger" onclick="toggleSidebar()">&#9776;</button>
    <h1>My Deals</h1>
  </div>
  
  <div class="nav-center">
    <div class="search-container">
        <input type="text" id="filter-product" placeholder="Search for amazing food deals..." oninput="applyFilters()">
    </div>
  </div>

  <div class="nav-right">
    <a href="d4d_results.html" style="text-decoration: none; padding: 8px 16px; border-radius: 20px; font-weight: 600; font-size: 14px; background: #f1f3f4; color: #202124; border: 1px solid #dadce0;">🛒 Groceries</a>
    <a href="cobone_results.html" style="text-decoration: none; padding: 8px 16px; border-radius: 20px; font-weight: 600; font-size: 14px; background: #1a73e8; color: #ffffff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); pointer-events: none;">🍽️ Food</a>
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
        <option value="offer-desc" selected>Highest Offer % + Newest</option>
        <option value="store-asc">Store/Restaurant (A to Z)</option>
        <option value="price-asc">Price: Low to High</option>
        <option value="price-desc">Price: High to Low</option>
    </select>
</div>

    <div class="filter-group">
      <label>Max Price</label>
      <div class="slider-container">
        <input type="range" id="filter-price" min="0" max="10000" value="10000" step="5" oninput="applyFilters()">
        <span id="price-range-label"><span class="currency-icon-small">&#x20C1;</span>10,000</span>
      </div>
    </div>
    
<div class="filter-group">
                <label>FILTER BRANDS / RESTAURANTS</label>
                <input type="text" id="storeSearchInput" class="store-search-box" placeholder="Find a restaurant..." onkeyup="filterStoreList()">
                
                <div class="checkbox-panel" id="store-checkboxes">
                    </div>
            </div>
            
    <button class="filter-btn" onclick="toggleSidebar()">Apply Filters</button>
    <button class="btn-reset" onclick="resetFilters()">Clear All Filters</button>
  </div>
</div>

<div class="main-wrapper">
  <div class="meta-bar">
    <span id="count">Loading deals...</span>
  </div>

  <div id="deal-grid" class="deal-grid">
  </div>
  <div id="sentinel" class="loading-indicator">Scroll down for more deals...</div>
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
  
  // CHUNK_SIZE adjusted to 10 to perfectly load 2 rows of 5 cards on laptops
  const CHUNK_SIZE = 10;

  const dealGrid = document.getElementById('deal-grid');
  const sentinel = document.getElementById('sentinel');
  const countLabel = document.getElementById('count');

  function formatDisplayDate(dateStr) {{
      if (!dateStr) return "";
      const parts = dateStr.split('-');
      if (parts.length !== 3) return dateStr;
      const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      const day = parts[2].padStart(2, '0');
      return `${{day}}/${{months[parseInt(parts[1], 10) - 1]}}/${{parts[0]}}`;
  }}

  function formatPriceNumber(num) {{
      if (num == null) return "";
      return Number(num).toLocaleString('en-US', {{ minimumFractionDigits: 0, maximumFractionDigits: 2 }});
  }}

  const rawStoreList = [];
  rawData.forEach(r => {{
      const storeName = r.Store || r.Restaurant;
      if (storeName) {{
          const parts = storeName.split("&").map(s => s.trim());
          rawStoreList.push(...parts);
      }}
  }});
  const stores = [...new Set(rawStoreList)].sort();
  
  const cbContainer = document.getElementById('store-checkboxes');
  stores.forEach(s => {{
    if(!s) return;
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
  document.getElementById('price-range-label').innerHTML = '<span class="currency-icon-small">&#x20C1;</span> ' + formatPriceNumber(maxPrice);

  const sidebar = document.getElementById('filterSidebar');
  const overlay = document.getElementById('sidebarOverlay');
  function toggleSidebar() {{
    sidebar.classList.toggle('open');
    overlay.classList.toggle('active');
  }}
  
  function getOfferVal(offerStr) {{
      if (!offerStr) return 0;
      const match = String(offerStr).match(/[\d.]+/);
      return match ? parseFloat(match[0]) : 0;
  }}

  function applyFilters() {{
    const searchQuery = document.getElementById('filter-product').value.toLowerCase().trim();
    const searchTokens = searchQuery.split(/\s+/).filter(token => token.length > 0);
    
    const sortVal     = document.getElementById('sortDropdown').value;
    const max         = parseFloat(slider.value);
    
    const checkedBoxes = Array.from(document.querySelectorAll('.store-cb:checked'));
    const selectedStores = checkedBoxes.map(cb => cb.value);

    document.getElementById('price-range-label').innerHTML = '<span class="currency-icon-small">&#x20C1;</span> ' + formatPriceNumber(max);

    filteredData = rawData.filter(item => {{
      const pName = item.Deal_Name || item.Product || item.Deal_Title || "Unknown item";
      const productName = pName.toLowerCase();
      
      let matchSearch = true;
      if (searchTokens.length > 0) {{
          matchSearch = searchTokens.every(token => productName.includes(token));
      }}

      const sName = item.Restaurant || item.Store || "";
      const matchStore  = selectedStores.length === 0 || selectedStores.some(selected => sName.includes(selected));
      const matchPrice  = (item.Price === null) || (item.Price <= max);
      
      return matchSearch && matchStore && matchPrice;
    }});

    if (sortVal === 'price-asc') {{
        filteredData.sort((a, b) => (a.Price || 0) - (b.Price || 0));
    }} else if (sortVal === 'price-desc') {{
        filteredData.sort((a, b) => (b.Price || 0) - (a.Price || 0));
    }} else if (sortVal === 'store-asc') {{
        filteredData.sort((a, b) => (a.Restaurant || a.Store || "").localeCompare(b.Restaurant || b.Store || ""));
    }} else if (sortVal === 'offer-desc') {{
        filteredData.sort((a, b) => {{
            const offerDiff = getOfferVal(b.Offer) - getOfferVal(a.Offer);
            if (offerDiff !== 0) return offerDiff;
            
            const dateA = a.Fetched_Date || "";
            const dateB = b.Fetched_Date || "";
            return dateB.localeCompare(dateA);
        }});
    }}

    currentIndex = 0;
    dealGrid.innerHTML = ''; 
    
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
      const card = document.createElement('div');
      card.className = 'card';
      
      const pName = item.Deal_Name || item.Product || item.Deal_Title || "Unknown item";
      const sName = item.Restaurant || item.Store || "Unknown place";
      
      // Pull URL from scraped dataset, fallback to # if missing
      const dealUrl = item.Deal_URL || item.URL || item.Link || "#";
      const safeName = pName.replace(/'/g, "&apos;").replace(/"/g, "&quot;");
      
      const imgTag = item.Image_URL 
          ? `<img src="${{item.Image_URL}}" alt="${{safeName}}" loading="lazy" onclick="openPopup('${{item.Image_URL}}', '${{safeName}}')">` 
          : "No image";

      const priceHtml = item.Price 
          ? `<div class="price-badge"><span class="currency-icon">&#x20C1;</span><span class="card-price">${{formatPriceNumber(item.Price)}}</span></div>` 
          : "";
          
      const oldPriceHtml = item.Old_Price ? `<span class="card-old-price"><span class="currency-icon-small">&#x20C1;</span>${{formatPriceNumber(item.Old_Price)}}</span>` : "";
      const offerStr = item.Offer ? `<span class="badge-offer">${{item.Offer}}</span>` : "";

      const displayDate = formatDisplayDate(item.Fetched_Date);
      const fetchDate = item.Fetched_Date ? `Updated: ${{displayDate}}` : "";

      // Title wrapped in an <a> tag linking to the original deal
      card.innerHTML = `
          <div class="card-img-wrapper">${{imgTag}}</div>
          <a href="${{dealUrl}}" target="_blank" class="title-link" title="Go to Deal">
              <div class="card-title">${{pName}}</div>
          </a>
          <div class="card-price-row">
              ${{priceHtml}}
              ${{oldPriceHtml}}
              ${{offerStr}}
          </div>
          <div class="card-store">${{sName}}</div>
          <div class="card-date">${{fetchDate}}</div>
      `;
      fragment.appendChild(card);
    }});

    dealGrid.appendChild(fragment);
    currentIndex += chunk.length;
    
    countLabel.innerHTML = `Showing <strong>${{currentIndex}}</strong> of <strong>${{filteredData.length}}</strong> deals`;
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
    document.getElementById('sortDropdown').value = 'offer-desc'; 
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

    OUTPUT_HTML = Path("cobone_results.html")
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    log.info("Saved HTML → %s", OUTPUT_HTML)
    
async def main() -> None:
    # 1. Fetch Cobone Deals
    new_results = await scrape_cobone(TARGET_URL)
    log.info(f"🏁 Total valid Cobone deals extracted: {len(new_results)}")
    
    # ---> SMART HISTORY MERGER & 7-DAY RETENTION POLICY <---
    historical_data = []
    if OUTPUT_JSON.exists():
        try:
            raw_history = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
            if isinstance(raw_history, list):
                today_date = datetime.now()
                for item in raw_history:
                    date_str = item.get("Fetched_Date", "2000-01-01")
                    try:
                        item_date = datetime.strptime(date_str, "%Y-%m-%d")
                        if (today_date - item_date).days <= 7:
                            historical_data.append(item)
                    except ValueError:
                        pass
        except Exception:
            pass

    merged_dict = {}
    
    # Load history
    for item in historical_data:
        key = f"{item.get('Product', '').strip().lower()}|{item.get('Store', '').strip().lower()}"
        merged_dict[key] = item

    # Load fresh results
    for item in new_results:
        key = f"{item.get('Product', '').strip().lower()}|{item.get('Store', '').strip().lower()}"
        merged_dict[key] = item

    results = list(merged_dict.values())
        
    if results:
        OUTPUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        save_html(results)
        log.info("🎉 Done. %d total food deals saved to database.", len(results))
    else:
        log.warning("🚨 ZERO DEALS SAVED!")
        OUTPUT_JSON.write_text("[]", encoding="utf-8")
        save_html([])

if __name__ == "__main__":
    asyncio.run(main())
    
