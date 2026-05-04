import os
import asyncio
from supabase import create_client, Client
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

# Pull credentials from GitHub Secrets
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# The exact list of stores you want to KEEP
APPROVED_STORES = [
    "LULU Hypermarket", "Hyper Panda", "Othaim Markets", "Nesto", 
    "eXtra", "Danube", "Mark & Save", "Grand Hyper", 
    "Hyper Al Wafa", "Al Madina Hypermarket", "Jarir Bookstore"
]

def clean_database():
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.error("❌ Missing Supabase credentials in environment variables.")
        return

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    log.info("☁️ Connected to Supabase. Starting cleaning process...")

    try:
        # Step 1: Download ALL rows from the database (using the pagination trick)
        all_rows = []
        offset = 0
        limit = 1000
        
        while True:
            response = supabase.table("ai_cache").select("*").range(offset, offset + limit - 1).execute()
            if not response.data:
                break
            all_rows.extend(response.data)
            if len(response.data) < limit:
                break
            offset += limit
            
        log.info(f"📊 Downloaded {len(all_rows)} total rows from the database.")

        # Step 2: Identify which rows belong to UNAPPROVED stores
        urls_to_delete = []
        for row in all_rows:
            # We need to extract the store name. 
            # Since your database currently only saves "image_url" and "product_name", 
            # we have to look for the store name inside the image URL itself!
            
            image_url = row.get("image_url", "")
            
            # Check if ANY of the approved stores appear in the URL
            # Note: We convert to lowercase and replace spaces with hyphens to match URL formatting
            is_approved = False
            for store in APPROVED_STORES:
                url_friendly_store = store.lower().replace(" ", "-").replace("&", "")
                if url_friendly_store in image_url.lower():
                    is_approved = True
                    break
                    
            if not is_approved:
                urls_to_delete.append(image_url)

        log.info(f"🗑️ Found {len(urls_to_delete)} items belonging to unapproved stores.")

        # Step 3: Delete the bad rows in batches of 1000
        if urls_to_delete:
            log.info("Starting deletion...")
            for i in range(0, len(urls_to_delete), 1000):
                batch = urls_to_delete[i:i + 1000]
                supabase.table("ai_cache").delete().in_("image_url", batch).execute()
                log.info(f"✅ Deleted batch of {len(batch)} items.")
            
            log.info("🎉 Database cleaning complete!")
        else:
            log.info("✨ Database is already clean. No items to delete.")

    except Exception as e:
        log.error(f"❌ An error occurred: {e}")

if __name__ == "__main__":
    clean_database()
