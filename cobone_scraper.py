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

# 1. Create the food directory if it doesn't exist
os.makedirs("food", exist_ok=True)

# 2. Point outputs into the new food directory
OUTPUT_HTML = Path("food/index.html")
OUTPUT_JSON = Path("food/cobone_results.json")

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
<title>GoDeals | Food Offers</title>
<!-- CLEANED: Linking to central stylesheet -->
<link rel="stylesheet" href="/style.css">
<!-- CLEANED: Linking to central navbar injection script -->
<script src="/nav.js" defer></script>
</head>
<body>

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
            
    <button class="filter-btn" style="padding: 12px; background: #1a73e8; color: #fff; border: none; border-radius: 8px; font-weight: 600; cursor: pointer; width: 100%;" onclick="toggleSidebar()">Apply Filters</button>
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
          rawStoreList.push(storeName.trim());
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
  
  window.toggleSidebar = function() {{
    sidebar.classList.toggle('open');
    overlay.classList.toggle('active');
  }};
  
  function getOfferVal(offerStr) {{
      if (!offerStr) return 0;
      const match = String(offerStr).match(/[\d.]+/);
      return match ? parseFloat(match[0]) : 0;
  }}

  window.applyFilters = function() {{
    const searchInput = document.getElementById('filter-product');
    const searchQuery = searchInput ? searchInput.value.toLowerCase().trim() : "";
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
    if (dealGrid) dealGrid.innerHTML = ''; 
    
    loadMore();
  }};

  function loadMore() {{
    if (!dealGrid || !sentinel) return;
    
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

  setTimeout(() => {{
      const observer = new IntersectionObserver((entries) => {{
        if (entries[0].isIntersecting) {{
            loadMore();
        }}
      }}, {{ rootMargin: "200px" }}); 
      
      if (sentinel) observer.observe(sentinel);
      applyFilters();
  }}, 100);

  window.resetFilters = function() {{
    const searchInput = document.getElementById('filter-product');
    if (searchInput) searchInput.value = '';
    
    document.getElementById('sortDropdown').value = 'offer-desc'; 
    document.getElementById('storeSearchInput').value = '';
    document.querySelectorAll('.store-cb').forEach(cb => cb.checked = false);
    slider.value = maxPrice;
    filterStoreList();
    applyFilters();
  }};

  window.filterStoreList = function() {{
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
  }};

  window.openPopup = function(src, title) {{
    const img = document.getElementById('popup-img');
    img.src = src;
    img.classList.remove('zoomed'); 
    
    document.getElementById('popup-title').innerHTML = title;
    
    document.getElementById('popup-overlay').classList.add('active');
  }};

  window.toggleZoom = function(e) {{
    e.stopPropagation(); 
    const img = document.getElementById('popup-img');
    img.classList.toggle('zoomed');
  }};

  window.closePopup = function(e) {{
    if (e && e.target && e.target.id === 'popup-img') return;
    
    if (!e || e.target === document.getElementById('popup-overlay') || e.currentTarget === document.getElementById('popup-close')) {{
      document.getElementById('popup-overlay').classList.remove('active');
    }}
  }};

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
    
async def main() -> None:
    new_results = await scrape_cobone(TARGET_URL)
    log.info(f"🏁 Total valid Cobone deals extracted: {len(new_results)}")
    
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
        log.info("🎉 Done. %d total food deals saved to database.", len(results))
    else:
        log.warning("🚨 ZERO DEALS SAVED!")
        OUTPUT_JSON.write_text("[]", encoding="utf-8")
        save_html([])

if __name__ == "__main__":
    asyncio.run(main())
