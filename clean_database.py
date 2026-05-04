import os
import logging
from supabase import create_client, Client

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger(__name__)

# Pull credentials from GitHub Secrets
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

def factory_reset_database():
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.error("❌ Missing Supabase credentials.")
        return

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    log.info("☁️ Connected to Supabase. Initiating Database Wipe...")

    try:
        total_deleted = 0
        while True:
            # Fetch 500 rows at a time
            response = supabase.table("ai_cache").select("image_url").limit(500).execute()
            rows = response.data
            
            if not rows:
                break # We are out of rows, the database is empty!
                
            urls_to_delete = [row["image_url"] for row in rows]
            
            # Delete in small safe chunks of 50 to prevent the "URL too long" crash!
            for i in range(0, len(urls_to_delete), 50):
                batch = urls_to_delete[i:i + 50]
                supabase.table("ai_cache").delete().in_("image_url", batch).execute()
                
            total_deleted += len(urls_to_delete)
            log.info(f"🗑️ Trashed {total_deleted} items so far...")
            
        log.info("🎉 Database wiped completely clean!")
        log.info("Next time your scraper runs, it will rebuild memory perfectly using ONLY your approved stores.")

    except Exception as e:
        log.error(f"❌ An error occurred: {e}")

if __name__ == "__main__":
    factory_reset_database()
