import os
import re
import sqlite3
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
DB_NAME = "jobs.db"

def _normalize_company(company_name):
    return " ".join((company_name or "").casefold().split())


def _normalize_domain(domain):
    value = (domain or "").strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/", 1)[0].split(":", 1)[0].strip(".")
    if value.startswith("www."):
        value = value[4:]
    if not value or "." not in value or any(char.isspace() for char in value):
        raise ValueError("Provide a verified domain such as example.com, not a company name or URL path.")
    return value


def _ensure_columns(cursor, table, definitions):
    existing = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in definitions.items():
        if name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_contacts_db(db_name=DB_NAME):
    conn = sqlite3.connect(db_name)
    try:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS contacts (
                id TEXT PRIMARY KEY,
                company TEXT,
                first_name TEXT,
                last_name TEXT,
                title TEXT,
                email TEXT,
                status TEXT DEFAULT 'NEW',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        _ensure_columns(cursor, "contacts", {
            "job_id": "TEXT",
            "company_domain": "TEXT",
        })
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS verified_company_domains (
                company_key TEXT PRIMARY KEY,
                company_name TEXT NOT NULL,
                domain TEXT NOT NULL,
                verification_source TEXT NOT NULL,
                verified_at TIMESTAMP NOT NULL
            )
        """)
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_verified_company_domain_name ON verified_company_domains (LOWER(domain), company_key)")
        conn.commit()
    finally:
        conn.close()


def register_verified_company_domain(company_name, domain, verification_source, db_name=DB_NAME):
    """Register a domain only after the operator verifies it from a reliable source."""
    company_key = _normalize_company(company_name)
    normalized_domain = _normalize_domain(domain)
    source = (verification_source or "").strip()
    if not company_key or len(source) < 3:
        raise ValueError("Company name and a meaningful verification source are required.")

    init_contacts_db(db_name)
    conn = sqlite3.connect(db_name)
    try:
        conn.execute("""
            INSERT INTO verified_company_domains
                (company_key, company_name, domain, verification_source, verified_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(company_key) DO UPDATE SET
                company_name = excluded.company_name,
                domain = excluded.domain,
                verification_source = excluded.verification_source,
                verified_at = excluded.verified_at
        """, (company_key, company_name.strip(), normalized_domain, source, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()


def _verified_domain_for_company(cursor, company_name):
    cursor.execute(
        "SELECT domain FROM verified_company_domains WHERE company_key = ?",
        (_normalize_company(company_name),),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def _domain_matches(value, verified_domain):
    if not value:
        return False
    try:
        observed = _normalize_domain(value)
    except ValueError:
        return False
    return observed == verified_domain or observed.endswith("." + verified_domain)


def _email_matches_domain(email, verified_domain):
    parts = (email or "").rsplit("@", 1)
    return len(parts) == 2 and bool(parts[0]) and _domain_matches(parts[1], verified_domain)


def _person_organization_domain(person):
    organization = person.get("organization") or {}
    if not isinstance(organization, dict):
        return None
    return organization.get("primary_domain") or organization.get("domain") or organization.get("website_url")


def _best_tailored_job(cursor, company_name):
    cursor.execute("""
        SELECT id, company FROM jobs
        WHERE LOWER(TRIM(company)) = LOWER(TRIM(?))
          AND status = 'TAILORED'
          AND tailored_resume IS NOT NULL AND TRIM(tailored_resume) != ''
        ORDER BY COALESCE(match_score, 0) DESC, id
        LIMIT 1
    """, (company_name,))
    return cursor.fetchone()


def _resolve_domain_and_job(cursor, company_name, verified_domain):
    stored_domain = _verified_domain_for_company(cursor, company_name)
    if verified_domain:
        requested_domain = _normalize_domain(verified_domain)
        if stored_domain != requested_domain:
            print(f"Skipping {company_name}: supplied domain is not registered as verified.")
            return None, None
    else:
        requested_domain = stored_domain
    if not requested_domain:
        print(f"Skipping Apollo lookup for {company_name}: no verified company domain is registered.")
        return None, None

    tailored_job = _best_tailored_job(cursor, company_name)
    if not tailored_job:
        print(f"Skipping Apollo lookup for {company_name}: no tailored job is available to associate contacts with.")
        return None, None
    return requested_domain, tailored_job[0]


def _search_apollo(company_name, domain):
    url = "https://api.apollo.io/v1/people/search"
    headers = {"Cache-Control": "no-cache", "Content-Type": "application/json"}
    payload = {
        "api_key": APOLLO_API_KEY,
        "q_organization_domains": domain,
        "person_titles": ["Recruiter", "Talent Acquisition", "Engineering Manager", "Founder", "CTO"],
        "page": 1,
        "per_page": 5,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=10)
    if response.status_code != 200:
        print(f"Apollo API error for {company_name}: {response.status_code}")
        return []
    return response.json().get("people", [])


def _store_verified_people(cursor, company_name, domain, job_id, people):
    accepted_contacts = []
    for person in people:
        email = (person.get("email") or "").strip()
        if (
            not _email_matches_domain(email, domain)
            or not _domain_matches(_person_organization_domain(person), domain)
        ):
            continue
        contact_id = str(person.get("id") or email.lower())
        cursor.execute("""
            INSERT INTO contacts (id, company, first_name, last_name, title, email, job_id, company_domain)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                job_id = excluded.job_id,
                company_domain = excluded.company_domain
            WHERE LOWER(TRIM(contacts.company)) = LOWER(TRIM(excluded.company))
              AND LOWER(TRIM(contacts.email)) = LOWER(TRIM(excluded.email))
        """, (
            contact_id,
            company_name,
            person.get("first_name", ""),
            person.get("last_name", ""),
            person.get("title", ""),
            email,
            job_id,
            domain,
        ))
        if cursor.rowcount:
            accepted_contacts.append(person)
    return accepted_contacts


def enrich_company_contacts(company_name, verified_domain=None, db_name=DB_NAME):
    if not APOLLO_API_KEY:
        print("Apollo API Key missing.")
        return []

    init_contacts_db(db_name)
    conn = sqlite3.connect(db_name)
    try:
        cursor = conn.cursor()
        requested_domain, job_id = _resolve_domain_and_job(cursor, company_name, verified_domain)
        if not requested_domain or not job_id:
            return []
        people = _search_apollo(company_name, requested_domain)
        accepted_contacts = _store_verified_people(cursor, company_name, requested_domain, job_id, people)
        conn.commit()
        return accepted_contacts
    except Exception as exc:
        print(f"Exception during contact enrichment for {company_name}: {exc}")
        return []
    finally:
        conn.close()


def enrich_all_tailored_companies(db_name=DB_NAME):
    init_contacts_db(db_name)
    conn = sqlite3.connect(db_name)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT company FROM jobs WHERE status = 'TAILORED' AND company IS NOT NULL")
        companies = [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

    for company in companies:
        enrich_company_contacts(company, db_name=db_name)


if __name__ == "__main__":
    enrich_all_tailored_companies()