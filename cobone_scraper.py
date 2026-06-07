import asyncio
import json
import logging
import re
from datetime import datetime
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
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="en-US"
        )
        page = await context.new_page()
        log.info("🔍 Loading Cobone Riyadh Food Deals...")
        
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        # Scroll down to load all deals
        for _ in range(8):
            await page.mouse.wheel(0, 1500)
            await asyncio.sleep(1.5)
            
        html = await page.content()
        await browser.close()
        
    soup = BeautifulSoup(html, "html.parser")
    all_results = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    deals = soup.find_all("a", href=True)
    for a in deals:
        if "/deals/" not in a['href']: continue
        text_content = a.get_text(" | ", strip=True)
        if "SAR" not in text_content: continue
        
        img = a.find("img")
        if not img: continue
        image_url = img.get("src") or img.get("data-src") or ""
        if not image_url or "base64" in image_url: continue
        
        title = img.get("alt", "").strip() or a.get("title", "").strip()
        if not title:
            blocks = text_content.split(" | ")
            if blocks: title = blocks[0]
            
        if len(title) < 5: continue
            
        price_match = re.search(r'SAR[^\d]*(\d+)', text_content)
        price = float(price_match.group(1)) if price_match else None
        if not price: continue
        
        offer_match = re.search(r'(\d+)\s*%', text_content)
        offer = f"{offer_match.group(1)}% Off" if offer_match else ""
        
        store_name = "Cobone Food Deal"
        if "Sold" in text_content:
            store_parts = text_content.split("|")
            for i, part in enumerate(store_parts):
                if "Sold" in part and i > 0:
                    store_name = store_parts[i-1].strip()
                    break
        
        deal_link = "https://www.cobone.com" + a['href'] if a['href'].startswith('/') else a['href']
        
        all_results.append({
            "Store": store_name,
            "Product": title,
            "Price": price,
            "Offer": offer,
            "Image_URL": image_url,
            "Deal_URL": deal_link,
            "Fetched_Date": today_str
        })
        
    return all_results

def save_html(data: List[Dict]) -> None:
    products_json = json.dumps(data, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Food Offers | Riyadh</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; background: #f5f7fa; color: #333; overflow-x: hidden; }}
  .navbar {{ display: flex; align-items: center; gap: 16px; background: #ffffff; padding: 16px 24px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); position: sticky; top: 0; z-index: 100; flex-wrap: wrap; }}
  .hamburger {{ background: none; border: none; font-size: 26px; cursor: pointer; color: #5f6368; display: flex; align-items: center; justify-content: center; padding: 4px 8px; border-radius: 8px; transition: background 0.2s; }}
  .hamburger:hover {{ background: #f1f3f4; color: #202124; }}
  h1 {{ color: #202124; font-size: 22px; font-weight: 600; letter-spacing: -0.5px; white-space: nowrap; }}
  
  /* Navigation Tabs */
  .nav-tabs {{ display: flex; gap: 8px; margin-left: 20px; flex-wrap: wrap; }}
  .nav-tabs a {{ text-decoration: none; padding: 6px 14px; border-radius: 20px; font-weight: 600; font-size: 14px; transition: all 0.2s; }}
  .tab-inactive {{ background: #f1f3f4; color: #202124; border: 1px solid #dadce0; }}
  .tab-inactive:hover {{ background: #e8eaed; }}
  .tab-active {{ background: #1a73e8; color: #ffffff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); pointer-events: none; }}

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
  .filter-group.search-box {{ margin-left: auto; min-width: 200px; }}
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
  
  @media (max-width: 768px) {{
      .filter-group.search-box {{ margin-left: 0; width: 100%; margin-top: 10px; }}
  }}
</style>
</head>
<body>

<div class="navbar">
  <button class="hamburger" onclick="toggleSidebar()">&#9776;</button>
  <h1>My Deals</h1>

  <div class="nav-tabs">
    <a href="d4d_results.html" class="tab-inactive">🛒 Groceries</a>
    <a href="cobone_results.html" class="tab-active">🍽️ Food Offers</a>
  </div>

  <div class="filter-group search-box">
      <input type="text" id="filter-product" placeholder="Search food deals..." oninput="applyFilters()">
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
        <option value="store-asc">Restaurant Name (A to Z)</option>
        <option value="price-asc">Price: Low to High</option>
        <option value="price-desc">Price: High to Low</option>
    </select>
</div>

    <div class="filter-group">
      <label>Max Price</label>
      <div class="slider-container">
        <input type="range" id="filter-price" min="0" max="1000" value="1000" step="5" oninput="applyFilters()">
        <span id="price-range-label">SAR 1000</span>
      </div>
    </div>
    
<div class="filter-group">
    <label>FILTER RESTAURANTS</label>
    <input type="text" id="storeSearchInput" class="store-search-box" placeholder="Find a restaurant..." onkeyup="filterStoreList()">
    <div class="checkbox-panel" id="store-checkboxes"></div>
</div>
            
    <button class="btn-reset" onclick="resetFilters()">Clear All Filters</button>
  </div>
</div>

<div class="main-wrapper">
  <div class="meta-bar">
    <span id="count">Loading deals...</span>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>Image</th><th>Deal Name</th><th>Restaurant</th><th>Price</th><th>Offer</th></tr>
      </thead>
      <tbody id="tbody">
      </tbody>
    </table>
    <div id="sentinel" class="loading-indicator">Scroll down for more deals...</div>
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
  const maxPrice = prices.length ? Math.ceil(Math.max(...prices) / 10) * 10 : 1000;
  const slider = document.getElementById('filter-price');
  slider.max   = maxPrice;
  slider.value = maxPrice;
  document.getElementById('price-range-label').textContent = 'SAR ' + maxPrice;

  function toggleSidebar() {{
    document.getElementById('filterSidebar').classList.toggle('open');
    document.getElementById('sidebarOverlay').classList.toggle('active');
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
    }} else if (sortVal === 'store-asc') {{
        filteredData.sort((a, b) => (a.Store || "").localeCompare(b.Store || ""));
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
      const imgTag = item.Image_URL ? `<img src="${{item.Image_URL}}" alt="${{safeName}}" loading="lazy">` : "No image";

      // CLickable Title pointing directly to Cobone!
      const titleHtml = item.Deal_URL 
          ? `<a href="${{item.Deal_URL}}" target="_blank" style="color: #1a73e8; text-decoration: none; font-weight: 600;">${{item.Product || "Unknown item"}}</a>`
          : `<div style="font-weight: 500;">${{item.Product || "Unknown item"}}</div>`;

      const fetchDate = item.Fetched_Date 
          ? `<div style="font-size: 12px; color: #80868b; margin-top: 6px; font-weight: 400;">Updated: ${{item.Fetched_Date}}</div>` 
          : "";

      tr.innerHTML = `
          <td>${{imgTag}}</td>
          <td>
             ${{titleHtml}}
             ${{fetchDate}}
          </td>
          <td>${{item.Store || "Unknown store"}}</td>
          <td>${{priceStr}}</td>
          <td>${{offerStr}}</td>
      `;
      fragment.appendChild(tr);
    }});

    tbody.appendChild(fragment);
    currentIndex += chunk.length;
    countLabel.innerHTML = `Showing <strong>${{currentIndex}}</strong> of <strong>${{filteredData.length}}</strong> deals`;
  }}

  const observer = new IntersectionObserver((entries) => {{
    if (entries[0].isIntersecting) {{ loadMore(); }}
  }}, {{ rootMargin: "200px" }}); 
  observer.observe(sentinel);

  applyFilters();

  function resetFilters() {{
    document.getElementById('filter-product').value = '';
    document.getElementById('sortDropdown').value = 'offer-desc'; 
    document.getElementById('storeSearchInput').value = '';
    document.querySelectorAll('.store-cb').forEach(cb => cb.checked = false);
    slider.value = maxPrice;
    applyFilters();
  }}

  function filterStoreList() {{
      let input = document.getElementById('storeSearchInput').value.toLowerCase();
      let storeLabels = document.querySelectorAll('.checkbox-label');
      storeLabels.forEach(label => {{
          let storeName = label.innerText.toLowerCase();
          label.style.display = storeName.includes(input) ? "flex" : "none";
      }});
  }}
</script>
</body>
</html>"""

    OUTPUT_HTML.write_text(html, encoding="utf-8")
    log.info("Saved HTML → %s", OUTPUT_HTML)

async def main() -> None:
    new_results = await scrape_cobone(TARGET_URL)
    
    historical_data = []
    if OUTPUT_JSON.exists():
        try:
            historical_data = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
            if not isinstance(historical_data, list): historical_data = []
        except Exception:
            historical_data = []

    merged_dict = {}
    for item in historical_data:
        key = f"{item.get('Product', '').strip().lower()}|{item.get('Store', '').strip().lower()}"
        merged_dict[key] = item

    for item in new_results:
        key = f"{item.get('Product', '').strip().lower()}|{item.get('Store', '').strip().lower()}"
        merged_dict[key] = item

    results = list(merged_dict.values())
        
    if results:
        OUTPUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        save_html(results)
        log.info("Done. %d food deals saved.", len(results))

if __name__ == "__main__":
    asyncio.run(main())
