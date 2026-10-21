import os
import datetime
from scraper import fetch_and_store_jobs, CORE_TITLES
from claude_engine import process_pending_jobs
from job_app_bot import apply_to_tailored_jobs
from apollo_enrichment import enrich_all_tailored_companies
from outreach import dispatch_outreach_campaign

def configure_environment_proxies():
    """Ensures proxies fetched from GitHub Actions are respected by underlying network libraries."""
    proxy_url = os.getenv("PROXY_URL") or os.getenv("HTTP_PROXY")
    if proxy_url:
        print(f"[Proxy Config] Active proxy detected: {proxy_url}")
        # Explicitly set standard environment variables so requests/curl/jobspy catch them
        os.environ["HTTP_PROXY"] = proxy_url
        os.environ["HTTPS_PROXY"] = proxy_url
    else:
        print("[Proxy Config] No proxy environment variable found. Running direct connection.")

def run_pipeline():
    # Configure proxies dynamically at runtime execution
    configure_environment_proxies()

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n==========================================")
    print(f" Starting Global Autonomous Engine [{timestamp}]")
    print(f" Target Titles: {len(CORE_TITLES)} specialized roles")
    print(f"==========================================")

    # Job #1 (Part A): Gather raw postings (1-week freshness filter) & Tailor via Claude 3.7
    print("\n[Job #1 - Step A] Aggregating Global Job Postings (Past Week)...")
    fetch_and_store_jobs(titles=CORE_TITLES, max_results_per_title=15)

    print("\n[Job #1 - Step B] Running Claude 3.7 Resume & Cover Letter Tailoring...")
    process_pending_jobs()

    # Job #1 (Part C): Execute actual job applications with generated PDF & cover letter
    print("\n[Job #1 - Step C] Executing Automated Job Applications...")
    apply_to_tailored_jobs()

    # Job #2 & #3: Enrich company decision-makers & Dispatch Referral/Executive Cold Outreach with attached PDF & Cover Letter
    print("\n[Job #2 & #3] Fetching Employee, Recruiter, & Executive Contacts via Apollo...")
    enrich_all_tailored_companies()

    print("\n[Job #2 & #3] Dispatching Referral & Executive Cold Outreach Campaigns...")
    dispatch_outreach_campaign()

    print(f"\nPipeline execution finished successfully at {datetime.datetime.now().strftime('%H:%M:%S')}.\n")

if __name__ == "__main__":
    run_pipeline()