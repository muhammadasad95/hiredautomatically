# Autonomous Global Job Search, Tailoring & Outreach Engine

An end-to-end, multi-agent AI pipeline designed to automate the global job hunting process. It continuously scrapes jobs across global markets, leverages **Claude 3.7** to intelligently tailor your resume and cover letter on a per-job basis, applies directly via automated web drivers, enriches company decision-maker contacts (**Apollo.io**), and dispatches personalized cold outreach via SMTP with dynamically generated PDF attachments.

---

## Key Features

- **Global Job Scraping:** Queries multiple job platforms (LinkedIn, Indeed, Glassdoor, ZipRecruiter, Bayt) across 18+ countries with strict 168-hour (1-week) freshness filters and proxy support.
- **AI Match & Tailoring (Claude 3.7):** Scores jobs against your master resume, extracts missing ATS keywords, and rewrites experience bullet points using Google's **XYZ formula** (*Accomplished [X], measured by [Y], by doing [Z]*).
- **Dynamic Document Generation:** Dynamically compiles role-specific PDF resumes (`fpdf2`) and custom cover letters just-in-time for applications and cold emails—**never modifying your original master resume**.
- **Automated Web Applications:** Automated browser interactions (`Playwright`) to handle target job portal submissions.
- **Decision-Maker Enrichment & Cold Outreach:** Finds recruiters, engineering managers, CTOs, and founders via Apollo.io and sends personalized cold emails requesting referrals or quick intro chats.

---

## Prerequisites & Requirements

- **Python:** Version `3.10` or higher.
- **Anthropic API Key:** Access to Claude 3.7 Sonnet (`claude-3-7-sonnet-20250219`).
- **Apollo.io API Key:** For fetching decision-maker emails.
- **SMTP Credentials:** Gmail App Password or custom SMTP server for outreach dispatch.
- **Proxy Server (Optional but Recommended):** To prevent rate limits (`429`) and IP blocks (`403`) from job portals.

---

## Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/your-repo-name.git
cd your-repo-name
```

### 2. Create and Activate a Virtual Environment
```bash
# macOS/Linux
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
python3 -m playwright install
```

---

## Configuration Guide

### Step 1: Add Your Master Resume
Place your master resume in the root folder as **`resume.pdf`**.
> **Note:** The system reads `resume.pdf` in read-only mode to extract your core profile details. It will **never** alter or overwrite this master file.

---

### Step 2: Configure Environment Variables
Create a `.env` file in the root project directory:

```bash
cp .env.example .env
```

Fill in your configuration details inside `.env`:

```env
# Anthropic Claude 3.7 API
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Apollo API (For Recruiter & Decision Maker Search)
APOLLO_API_KEY=your_apollo_api_key_here

# SMTP Configuration (For Cold Email & Referral Outreach)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=your_email@gmail.com
SMTP_PASSWORD=your_app_specific_password

# Proxy Configuration (Optional: Bypasses 403/429 Blocks)
PROXY_URL=http://user:pass@proxy.example.com:8080
# Alternatively, comma-separated proxies:
# PROXY_LIST=http://user:pass@ip1:port,http://user:pass@ip2:port
```

---

### Step 3: Customize Job Search & Profile Settings

#### 1. Target Titles & Global Regions (`scraper.py`)
Modify `CORE_TITLES` and `GLOBAL_COUNTRIES` in `scraper.py` to match your targeted job roles and locations:

```python
CORE_TITLES = [
    "Principal Software Engineer", "Staff Software Engineer", "Technical Lead", 
    "Solutions Architect", "Engineering Manager", "Director of Engineering"
]

GLOBAL_COUNTRIES = [
    "USA", "Canada", "UK", "Germany", "France", "Netherlands", 
    "Switzerland", "Singapore", "Australia", "United Arab Emirates"
]
```

#### 2. Master Header Details (`pdf_generator.py`)
Update the `ResumePDF` class header in `pdf_generator.py` with your personal details:

```python
class ResumePDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 16)
        self.cell(0, 8, 'Your Name', new_x="LMARGIN", new_y="NEXT", align='C')
        self.set_font('Helvetica', '', 10)
        self.cell(0, 5, 'Your Core Role / Specialization Title', new_x="LMARGIN", new_y="NEXT", align='C')
        self.ln(5)
```

---

## Running the Engine

### Process Existing Jobs

The orchestrator currently leaves scraping disabled so it can process listings already stored in `jobs.db` without repeating the long scrape. It tailors a bounded batch, enriches companies before listing review changes job statuses, reviews listings, then prepares outreach previews. It does not submit job applications, and SMTP is disabled unless explicitly opted in.

```bash
python3 cron_orchestrator.py
```

Claude tailoring is capped at 10 jobs per run by default. It prioritizes Remote IAM/identity, other remote, onsite/hybrid IAM/identity, then other onsite/hybrid jobs. Jobs whose work arrangement cannot be determined are held for review and are not sent to Claude by default. Each job uses one Claude call with the sequence: recruiter score/missing keywords/red flags → full résumé rewrite using supported XYZ evidence → ATS/hiring-manager stress-test and final complete résumé. Only the single final résumé is returned, reducing credits and avoiding duplicate drafts. Evidence citations, source dates/contact details, and source-supported numeric claims are validated before saving.

Optional environment settings:

```env
TAILOR_BATCH_LIMIT=10
TAILOR_INCLUDE_UNKNOWN_WORK_MODE=false
```

Increase the batch limit only after reviewing results and API cost. Setting `TAILOR_INCLUDE_UNKNOWN_WORK_MODE=true` allows uncertain listings into the bounded batch after the classified tiers.

The final document is the complete Step 3 résumé—not a highlights sheet stapled to the untouched master. It includes Step 1 score, missing keywords and red flags, Step 2 XYZ-style experience rewriting, and Step 3 ATS/hiring-manager findings and final rewrite. The PDF is typeset from that final résumé. Validation preserves candidate identity, source contact email, and employment years, and checks cited rewritten experience and numerical claims against source lines. Unsupported claims or missing evidence stop the save; genuine qualification gaps remain disclosed rather than disguised.

Claude receives the explicit target role and hiring company for each letter. A letter that is empty or does not name the target company is rejected; the job is not marked `TAILORED`.

Outreach is preview-only by default. It selects at most one new contact per company and applies conservative per-run and daily caps. Live sending requires both explicit settings below; do not enable these for a personal Gmail account until you have verified provider rules, contact eligibility, message content, and suppression behavior.

```env
OUTREACH_SEND_ENABLED=false
OUTREACH_DRY_RUN=true
OUTREACH_MAX_PER_RUN=5
OUTREACH_MAX_PER_DAY=5
```

Set `OUTREACH_SEND_ENABLED=true` and `OUTREACH_DRY_RUN=false` only when deliberately authorizing live SMTP sends. Daily counts use the local `outreach_events` table. Preview mode generates and records message previews but does not send, attach PDFs, or mark contacts as sent. One contact per company is selected per run; sent, in-flight, uncertain, and suppressed addresses are excluded. Live sends reserve each daily quota slot in SQLite before SMTP to prevent concurrent runs exceeding the cap. SMTP acceptance does not prove inbox delivery. An opt-out can be added to the durable suppression table with `add_to_outreach_suppression()`; automated reply/unsubscribe processing is not implemented yet.

Apollo enrichment no longer guesses a `.com` domain from the company name. Register a domain only after independently verifying it from a reliable source using `register_verified_company_domain(company_name, domain, verification_source)`. Apollo is skipped when no verified domain and tailored job exist; returned people are stored only when both Apollo's organization domain and the recipient email domain match. Contacts are linked to a specific tailored job, and outreach takes the resume and cover letter from that exact job. Existing contacts without these verified associations are excluded until enriched/linked again. This code does not automatically verify the provenance or legal eligibility of recipient data; review those before any live send.

### Module Breakdown

If you prefer to run specific steps individually:

1. **Scrape Global Jobs:**
   ```bash
   python3 scraper.py
   ```
2. **Tailor prioritized jobs via Claude:**
   ```bash
   python3 claude_engine.py
   ```
3. **Review prioritized job listings (not an automatic submission):**
   ```bash
   python3 job_app_bot.py
   ```
4. **Enrich Decision-Maker Emails:**
   ```bash
   python3 apollo_enrichment.py
   ```
5. **Prepare bounded outreach previews (SMTP disabled by default):**
   ```bash
   python3 outreach.py
   ```

---

## Database Management

All state, scraped listings, matching scores, tailored content, and outreach statuses are tracked inside **`jobs.db`** (`SQLite`).

### Status Pipeline Values

The following statuses are stored in different tables: job application states belong to `jobs`; `SENT`, `SEND_UNCERTAIN`, and opt-out suppression belong to outreach/contact tracking.

- **`PENDING`**: Raw scraped job awaiting tailoring.
- **`TAILORED`**: AI evaluation completed, tailored resume and cover letter generated.
- **`IN_PROGRESS`**: Job listing is being reviewed by the browser automation.
- **`NEEDS_MANUAL_ACTION`**: The system did not confirm an application submission; user action is still required.
- **`APPLIED`**: Legacy status only; do not assume it means a confirmed submission.
- **`SENT`**: Contact email was accepted by the configured SMTP server; this does not prove delivery or inbox placement.
- **`SEND_UNCERTAIN`**: SMTP outcome was ambiguous; automatic retry is suppressed to avoid duplicate sends.
- **`SKIPPED` / `FAILED`**: Missing descriptions or execution issues logged for review.

To reset job statuses or inspect records:
```bash
sqlite3 jobs.db "SELECT title, company, status, match_score FROM jobs;"
```

---

## Security & Best Practices

- **Never Commit Secrets:** Do not commit `.env`, `jobs.db`, or `resume.pdf` to version control.
- **Email Sending Limits:** Outreach is preview-only unless explicitly enabled and is capped at five per run and five per day by default. These are conservative code safeguards, not a guarantee of Gmail policy compliance or inbox delivery. Do not use a personal Gmail account for bulk cold outreach or artificial warm-up activity.