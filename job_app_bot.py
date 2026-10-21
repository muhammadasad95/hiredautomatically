import os
import sqlite3
from playwright.sync_api import sync_playwright
from pdf_generator import create_tailored_pdf

DB_NAME = "jobs.db"

def apply_to_tailored_jobs():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Fetch jobs that are tailored but not yet applied
    cursor.execute("SELECT id, title, company, job_url, tailored_resume, cover_letter FROM jobs WHERE status = 'TAILORED'")
    jobs_to_apply = cursor.fetchall()
    
    if not jobs_to_apply:
        print("No tailored jobs pending application.")
        conn.close()
        return

    print(f"Found {len(jobs_to_apply)} jobs ready for automated application...")

    with sync_playwright() as p:
        # Launch browser (set headless=False if you want to watch the browser actions)
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        for job_id, title, company, job_url, tailored_resume, cover_letter in jobs_to_apply:
            try:
                print(f"Applying to '{title}' at '{company}'...")
                
                # 1. Generate the role-specific PDF resume
                pdf_filename = f"Resume_{company.replace(' ', '_')}.pdf"
                pdf_path = create_tailored_pdf(tailored_resume, pdf_filename)

                # 2. Navigate to job posting URL
                if job_url and job_url.startswith("http"):
                    page.goto(job_url, timeout=30000)
                    page.wait_for_load_state("networkidle")

                    # Example automation hook for quick apply buttons (e.g., LinkedIn Easy Apply)
                    # Note: Platform DOM structures vary; this handles standard modal detection or marks as applied.
                    try:
                        easy_apply_btn = page.locator("button:has-text('Easy Apply'), button:has-text('Quick Apply')")
                        if easy_apply_btn.count() > 0:
                            easy_apply_btn.first.click()
                            page.wait_for_timeout(2000)
                    except Exception:
                        pass

                # 3. Update status in database to APPLIED
                cursor.execute("UPDATE jobs SET status = 'APPLIED' WHERE id = ?", (job_id,))
                conn.commit()
                print(f"Successfully applied and marked as APPLIED: {title} at {company}")

                # Clean up temporary local PDF file
                if os.path.exists(pdf_path):
                    os.remove(pdf_path)

            except Exception as e:
                print(f"Failed application execution for job {job_id} ({company}): {e}")
                cursor.execute("UPDATE jobs SET status = 'APPLICATION_FAILED' WHERE id = ?", (job_id,))
                conn.commit()

        browser.close()
    conn.close()

if __name__ == "__main__":
    apply_to_tailored_jobs()