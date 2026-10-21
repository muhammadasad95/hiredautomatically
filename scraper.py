# import os
# import sqlite3
# import pandas as pd
# from dotenv import load_dotenv
# from jobspy import scrape_jobs

# load_dotenv()

# # Parse proxies from .env
# PROXY_URL = os.getenv("PROXY_URL")
# PROXY_LIST = os.getenv("PROXY_LIST")

# def get_proxies():
#     """Returns a list or single string of proxies for JobSpy."""
#     if PROXY_LIST:
#         return [p.strip() for p in PROXY_LIST.split(",") if p.strip()]
#     elif PROXY_URL:
#         return PROXY_URL
#     return None

# PROXIES = get_proxies()

# DB_NAME = "jobs.db"

# # Core roles target list
# CORE_TITLES = [
#     "Principal Software Engineer", "Staff Software Engineer", "Technical Lead", 
#     "Tech Lead", "Lead Software Engineer", "Senior Principal Engineer",
#     "Solutions Architect", "Enterprise Architect", "Software Architect",
#     "Identity and Access Management Architect", "IAM Architect", "IAM Solutions Architect",
#     "Principal IAM Engineer", "Staff IAM Engineer", "Lead IAM Engineer", "Senior IAM Engineer",
#     "IAM Specialist", "Identity Architect", "Access Management Architect",
#     "Engineering Manager", "Director of Engineering", "VP of Engineering",
#     "Head of Engineering", "Head of Identity", "Director of IAM"
# ]

# GLOBAL_COUNTRIES = [
#     "USA", "Canada", "UK", "Germany", "France", "Netherlands", "Switzerland", 
#     "Sweden", "United Arab Emirates", "Saudi Arabia", "Qatar", "Singapore", 
#     "Australia", "Pakistan", "India", "Japan", "Brazil", "South Africa", "Ireland"
# ]

# def init_db():
#     conn = sqlite3.connect(DB_NAME)
#     cursor = conn.cursor()
#     cursor.execute('''
#         CREATE TABLE IF NOT EXISTS jobs (
#             id TEXT PRIMARY KEY,
#             title TEXT,
#             company TEXT,
#             location TEXT,
#             job_url TEXT,
#             description TEXT,
#             status TEXT DEFAULT 'PENDING',
#             match_score INTEGER,
#             missing_keywords TEXT,
#             red_flags TEXT,
#             tailored_resume TEXT,
#             cover_letter TEXT
#         )
#     ''')
#     conn.commit()
#     conn.close()

# def fetch_and_store_jobs(titles=CORE_TITLES, max_results_per_title=15):
#     init_db()
#     conn = sqlite3.connect(DB_NAME)
#     cursor = conn.cursor()
    
#     # Exclude naukri if not using specific proxies to keep queries clean
#     target_sites = ["linkedin", "indeed", "glassdoor", "zip_recruiter", "bayt"]

#     for title in titles:
#         print(f"\n==========================================")
#         print(f" Searching Role: '{title}' (Global)")
#         print(f"==========================================")
        
#         for country in GLOBAL_COUNTRIES:
#             try:
#                 # Scrape jobs with proxies and 168-hour (1 week) freshness filter
#                 jobs_df = scrape_jobs(
#                     site_name=target_sites,
#                     search_term=title,
#                     location=country,
#                     results_wanted=max_results_per_title,
#                     country_indeed=country,
#                     hours_old=720,
#                     proxies=PROXIES  # <--- Proxy injected here
#                 )

#                 if jobs_df is None or jobs_df.empty:
#                     continue

#                 added_count = 0
#                 for _, row in jobs_df.iterrows():
#                     job_id = f"{row.get('company', '')}_{row.get('title', '')}_{row.get('location', '')}".lower().replace(" ", "_")
                    
#                     cursor.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
#                     if cursor.fetchone() is None:
#                         cursor.execute('''
#                             INSERT INTO jobs (id, title, company, location, job_url, description, status)
#                             VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
#                         ''', (
#                             job_id,
#                             str(row.get('title', '')),
#                             str(row.get('company', '')),
#                             str(row.get('location', '')),
#                             str(row.get('job_url', '')),
#                             str(row.get('description', '')),
#                         ))
#                         added_count += 1
                
#                 conn.commit()
#                 print(f"  └ [{country}] Added {added_count} new postings for '{title}'")

#             except Exception as e:
#                 print(f"  └ [{country}] Search failed: {e}")

#     conn.close()

# if __name__ == "__main__":
#     fetch_and_store_jobs()

import os
import time
import random
import sqlite3
import pandas as pd
from jobspy import scrape_jobs

DB_NAME = "jobs.db"

# Core roles target list
CORE_TITLES = [
    "Principal Software Engineer", "Staff Software Engineer", "Technical Lead", 
    "Tech Lead", "Lead Software Engineer", "Senior Principal Engineer",
    "Solutions Architect", "Enterprise Architect", "Software Architect",
    "Identity and Access Management Architect", "IAM Architect", "IAM Solutions Architect",
    "Principal IAM Engineer", "Staff IAM Engineer", "Lead IAM Engineer", "Senior IAM Engineer",
    "IAM Specialist", "Identity Architect", "Access Management Architect",
    "Engineering Manager", "Director of Engineering", "VP of Engineering",
    "Head of Engineering", "Head of Identity", "Director of IAM"
]

GLOBAL_COUNTRIES = [
    "USA", "Canada", "UK", "Germany", "France", "Netherlands", "Switzerland", 
    "Sweden", "United Arab Emirates", "Saudi Arabia", "Qatar", "Singapore", 
    "Australia", "Pakistan", "India", "Japan", "Brazil", "South Africa", "Ireland"
]

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            title TEXT,
            company TEXT,
            location TEXT,
            job_url TEXT,
            description TEXT,
            status TEXT DEFAULT 'PENDING',
            match_score INTEGER,
            missing_keywords TEXT,
            red_flags TEXT,
            tailored_resume TEXT,
            cover_letter TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_supported_sites(country):
    """Dynamically picks compatible platforms to prevent 403 blocks or country mismatch exceptions."""
    sites = ["linkedin", "indeed"]
    
    # ZipRecruiter supports US and Canada only
    if country in ["USA", "Canada"]:
        sites.append("zip_recruiter")
        
    # Glassdoor supported countries list
    glassdoor_supported = ["USA", "Canada", "UK", "France", "Germany", "Netherlands", "Switzerland", "Sweden", "Singapore", "Australia", "Ireland"]
    if country in glassdoor_supported:
        sites.append("glassdoor")
        
    # Bayt targets MENA region
    mena_countries = ["United Arab Emirates", "Saudi Arabia", "Qatar"]
    if country in mena_countries:
        sites.append("bayt")
        
    return sites

def fetch_and_store_jobs(titles=CORE_TITLES, max_results_per_title=15):
    init_db()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    for title in titles:
        print(f"\n==========================================")
        print(f" Searching Role: '{title}' (Global)")
        print(f"==========================================")
        
        for country in GLOBAL_COUNTRIES:
            target_sites = get_supported_sites(country)
            try:
                # Scrape jobs directly with 720-hour (30 days) freshness filter
                jobs_df = scrape_jobs(
                    site_name=target_sites,
                    search_term=title,
                    location=country,
                    results_wanted=max_results_per_title,
                    country_indeed=country,
                    hours_old=720  # 30 days freshness window
                )

                if jobs_df is None or jobs_df.empty:
                    # Brief randomized pause even on empty returns to mimic human pacing
                    time.sleep(random.uniform(2.0, 4.0))
                    continue

                added_count = 0
                for _, row in jobs_df.iterrows():
                    job_id = f"{row.get('company', '')}_{row.get('title', '')}_{row.get('location', '')}".lower().replace(" ", "_")
                    
                    cursor.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
                    if cursor.fetchone() is None:
                        cursor.execute('''
                            INSERT INTO jobs (id, title, company, location, job_url, description, status)
                            VALUES (?, ?, ?, ?, ?, ?, 'PENDING')
                        ''', (
                            job_id,
                            str(row.get('title', '')),
                            str(row.get('company', '')),
                            str(row.get('location', '')),
                            str(row.get('job_url', '')),
                            str(row.get('description', '')),
                        ))
                        added_count += 1
                
                conn.commit()
                print(f"  └ [{country}] via {target_sites} -> Added {added_count} new postings for '{title}'")

                # Mandatory cooldown pause between requests to prevent 429/403 blocks
                time.sleep(random.uniform(4.0, 8.0))

            except Exception as e:
                print(f"  └ [{country}] Search failed: {e}")
                time.sleep(5.0)

    conn.close()

if __name__ == "__main__":
    fetch_and_store_jobs()