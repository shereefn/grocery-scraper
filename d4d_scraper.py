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
from typing import Optional, List, Dict, Tuple

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
EMAIL_APP_PASSWORD = os.environ.get("EMAIL_APP_PASSWORD")

# --- EMAIL ALERT SETTINGS ---
SENDER_EMAIL = "itzshereef@gmail.com"
RECEIVER_EMAIL = "shereefneikkan@gmail.com"

# ADD YOUR CUSTOM ALERTS HERE! 
PRICE_ALERTS = [
    {"keyword": "anchor milk powder 2.25", "max_price": 40.0},
    {"keyword": "Tide Detergent Powder 5", "max_price": 35.0},
    {"keyword": "Galaxy Jewels 650", "max_price": 35.0},
    {"keyword": "Abu Kass 10", "max_price": 50.0},
    {"keyword": "Liquid Detergent 2.8", "max_price": 28.0},
    {"keyword": "Ival Drinking Water 40", "max_price": 10.0},
    {"keyword": "Oska Drinking Water 40", "max_price": 10.0},
    {"keyword": "Noor Sunflower Oil 2x1.5 500ml", "max_price": 35.0},
    {"keyword": "Tide Detergent Liquid 1.8L", "max_price": 17.0},
    {"keyword": "Arial Detergent Liquid 1.8L", "max_price": 17.0},
    {"keyword": "Long Life Milk 1L", "max_price": 44.0} 
]

SEARCH_URL    = "https://d4donline.com/en/saudi-arabia/riyadh/products"
CARD_SELECTOR = "a.product-card"

TEST_STORES = [
    "LULU Hypermarket", "Hyper Panda", "Othaim Markets", "Nesto", 
    "eXtra", "Danube", "Mark & Save", "Grand Hyper", 
    "Hyper Al Wafa", "Al Madina Hypermarket", "Jarir Bookstore"
]
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
        </style>
    </head>
    <body class="container">
        <h2>Your Deal Alerts for Today:</h2>
        <hr style="border: 0; border-top: 1px solid #ddd; margin-bottom: 20px;">
    """

    for deal in found_deals:
        product_url_enlarge = deal['image']
        safe_name = deal['product_name'].replace('"', '&quot;')

        html_body += f"""
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
        <div style="text-align: center; margin-top: 30px; margin-bottom: 30px;">
            <a href="https://shereefn.github.io/grocery-scraper/d4d_results.html" style="display: inline-block; padding: 14px 28px; background-color: #1a73e8; color: #ffffff !important; text-decoration: none; border-radius: 8px; font-weight: bold; font-family: Arial, sans-serif; font-size: 16px;">View All Deals on Website</a>
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

def clean_price(raw) -> Optional[float]:
    if raw is None: return None
    if isinstance(raw, (int, float)): return float(raw)
    raw = str(raw)
    raw = re.sub(r"⚠.*", "", raw, flags=re.DOTALL).strip()
    raw = raw.replace(",", "").replace("،", "").replace("٬", "")
    matches = re.findall(r"\d+(?:\.\d+)?", raw)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None

def extract_price(card) -> Optional[float]:
    amt_elem = card.find(class_="product-amount")
    if amt_elem and amt_elem.get_text(strip=True):
        return clean_price(amt_elem.get_text(" ", strip=True))
        
    wrapper = card.find(class_="price-wrapper")
    if wrapper and wrapper.get_text(strip=True):
        return clean_price(wrapper.get_text(" ", strip=True))
        
    return None

def parse_ai_result(raw_val: str) -> Tuple[str, Optional[float]]:
    try:
        data = json.loads(raw_val)
        return data.get("name", "Unknown item"), data.get("price")
    except json.JSONDecodeError:
        pass
        
    if "||" in raw_val:
        parts = raw_val.split("||", 1)
        name = parts[0].strip()
        price_str = parts[1].strip()
        price = clean_price(price_str) if price_str.lower() != "none" else None
        return name, price
        
    if "|" in raw_val:
        parts = raw_val.split("|", 1)
        name = parts[0].strip()
        price_str = parts[1].strip()
        price = clean_price(price_str) if price_str.lower() != "none" else None
        return name, price
        
    return raw_val.strip(), None


async def read_product_name_from_image(image_url: str, http_client: httpx.AsyncClient) -> str:
    if not image_url:
        return '{"name": "Unknown item", "price": null}'
        
    max_retries = 6 
    for attempt in range(max_retries):
        try:
            resp = await http_client.get(image_url, timeout=15)
            if resp.status_code != 200:
                return '{"name": "Unknown item", "price": null}'

            prompt = (
                "You are a data extractor. Look at this grocery product image. "
                "1. Extract the Brand Name, Product Name, and Weight/Volume in English. "
                "2. Look for a highly visible promotional price painted on the image (e.g. 1.95 or 10.00). "
                "Output ONLY a raw, valid JSON object in this exact format: {\"name\": \"Extracted Name\", \"price\": 1.95} "
                "If you cannot find a price, use null for the price. Do not include markdown code blocks or any other text."
            )

            response = await client.aio.models.generate_content(
                model='gemini-2.5-flash-lite',
                contents=[
                    types.Part.from_bytes(data=resp.content, mime_type='image/jpeg'),
                    prompt
                ]
            )
            
            raw = response.text.strip()
            if raw.startswith("
http://googleusercontent.com/immersive_entry_chip/0
http://googleusercontent.com/immersive_entry_chip/1
