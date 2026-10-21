import datetime
from scraper import fetch_and_store_jobs, CORE_TITLES
from claude_engine import process_pending_jobs
from job_app_bot import apply_to_tailored_jobs
from apollo_enrichment import enrich_all_tailored_companies
from outreach import dispatch_outreach_campaign

def run_pipeline():
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n==========================================")
    print(f" Starting Global Autonomous Engine [{timestamp}]")
    print(f" Target Titles: {len(CORE_TITLES)} specialized roles")
    print("==========================================")

    # Job #1 (Part A): Gather raw postings & Tailor via Claude
    print("\n[Job #1 - Step A] Aggregating Global Job Postings (Past Week)...")
    #fetch_and_store_jobs(titles=CORE_TITLES, max_results_per_title=15)

    print("\n[Job #1 - Step B] Running Claude Resume & Cover Letter Tailoring...")
    process_pending_jobs()

    # Enrichment must run before review changes job states out of TAILORED.
    print("\n[Job #2] Fetching Employee, Recruiter, & Executive Contacts via Apollo...")
    enrich_all_tailored_companies()

    # The browser step currently reviews listings but does not submit applications.
    print("\n[Job #1 - Step C] Reviewing prioritized job listings...")
    apply_to_tailored_jobs()

    # Outreach is preview-only unless explicitly enabled in environment settings.
    print("\n[Job #3] Preparing bounded outreach previews (SMTP disabled by default)...")
    dispatch_outreach_campaign()

    print(f"\nPipeline execution finished successfully at {datetime.datetime.now().strftime('%H:%M:%S')}.\n")

if __name__ == "__main__":
    run_pipeline()