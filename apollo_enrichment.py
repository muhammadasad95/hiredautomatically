import os
import json
import sqlite3
import requests
from dotenv import load_dotenv

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
DB_NAME = "jobs.db"

def init_contacts_db():
    conn = sqlite3.connect(DB_NAME)
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
    conn.commit()
    conn.close()

def enrich_company_contacts(company_name):
    if not APOLLO_API_KEY:
        print("Apollo API Key missing.")
        return []

    url = "https://api.apollo.io/v1/people/search"
    headers = {
        "Cache-Control": "no-cache",
        "Content-Type": "application/json"
    }
    payload = {
        "api_key": APOLLO_API_KEY,
        "q_organization_domains": f"{company_name.lower().replace(' ', '')}.com",
        "person_titles": ["Recruiter", "Talent Acquisition", "Engineering Manager", "Founder", "CTO"],
        "page": 1,
        "per_page": 5
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            people = response.json().get('people', [])
            contacts = []
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()

            for person in people:
                email = person.get('email')
                if email:
                    contact_id = person.get('id', email)
                    cursor.execute('''
                        INSERT OR IGNORE INTO contacts (id, company, first_name, last_name, title, email)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        contact_id,
                        company_name,
                        person.get('first_name', ''),
                        person.get('last_name', ''),
                        person.get('title', ''),
                        email
                    ))
                    contacts.append(person)
            
            conn.commit()
            conn.close()
            return contacts
        else:
            print(f"Apollo API error for {company_name}: {response.status_code}")
            return []
    except Exception as e:
        print(f"Exception during contact enrichment for {company_name}: {e}")
        return []

def enrich_all_tailored_companies():
    init_contacts_db()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT company FROM jobs WHERE status = 'TAILORED'")
    companies = cursor.fetchall()
    conn.close()

    for (company,) in companies:
        print(f"Searching decision maker emails for {company}...")
        enrich_company_contacts(company)

if __name__ == "__main__":
    enrich_all_tailored_companies()