import sqlite3
from playwright.sync_api import sync_playwright
from job_priority import classify_priority_tier, job_priority_key

DB_NAME = "jobs.db"

def apply_to_tailored_jobs():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    columns = {row[1] for row in cursor.execute("PRAGMA table_info(jobs)").fetchall()}
    posted_select = ", date_posted" if "date_posted" in columns else ", NULL"
    cursor.execute(
        "SELECT id, title, company, job_url, description, location, match_score" + posted_select
        + " FROM jobs WHERE status = 'TAILORED'"
    )
    eligible_jobs = []
    review_count = 0
    for job in cursor.fetchall():
        job_id, title, company, job_url, description, location, match_score, date_posted = job
        tier, _label, _work_mode, _is_identity = classify_priority_tier(title, description, location)
        if tier == 4:
            review_count += 1
            print(
                f"Holding '{title}' at '{company}' for review: work arrangement is unknown."
            )
            continue
        eligible_jobs.append((job, job_priority_key(
            title, description, location, match_score, date_posted, job_id
        )))

    eligible_jobs.sort(key=lambda item: item[1])
    jobs_to_apply = [item[0] for item in eligible_jobs[:100]]
    
    if not jobs_to_apply:
        print(f"No confirmed-work-mode tailored jobs ready for processing ({review_count} held for review).")
        conn.close()
        return

    print(
        f"Found {len(eligible_jobs)} eligible tailored jobs; processing the top "
        f"{len(jobs_to_apply)} in priority order. {review_count} unknown-work-mode jobs held for review."
    )

    with sync_playwright() as p:
        # Launch browser (set headless=False if you want to watch the browser actions)
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        for job_id, title, company, job_url, _description, _location, _match_score, _date_posted in jobs_to_apply:
            try:
                print(f"Reviewing '{title}' at '{company}'...")
                cursor.execute("UPDATE jobs SET status = 'IN_PROGRESS' WHERE id = ?", (job_id,))
                conn.commit()

                # Visiting a listing is not an application. Do not click apply or
                # mark the job submitted until form completion is implemented and confirmed.
                if job_url and job_url.startswith("http"):
                    page.goto(job_url, timeout=30000)
                    page.wait_for_load_state("networkidle")
                cursor.execute("UPDATE jobs SET status = 'NEEDS_MANUAL_ACTION' WHERE id = ?", (job_id,))
                conn.commit()
                print(f"Listing reviewed; application not submitted: {title} at {company}")

            except Exception as e:
                print(f"Failed to review job {job_id} ({company}): {e}")
                cursor.execute("UPDATE jobs SET status = 'APPLICATION_FAILED' WHERE id = ?", (job_id,))
                conn.commit()

        browser.close()
    conn.close()

if __name__ == "__main__":
    apply_to_tailored_jobs()