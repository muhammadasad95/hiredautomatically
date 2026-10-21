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

### Full Automated Execution
To run the complete 3-job pipeline from scraping through tailoring, auto-applying, and dispatching outreach emails:

```bash
python3 cron_orchestrator.py
```

### Module Breakdown
If you prefer to run specific steps individually:

1. **Scrape Global Jobs:**
   ```bash
   python3 scraper.py
   ```
2. **Tailor Resumes & Cover Letters via Claude 3.7:**
   ```bash
   python3 claude_engine.py
   ```
3. **Execute Web Applications:**
   ```bash
   python3 job_app_bot.py
   ```
4. **Enrich Decision-Maker Emails:**
   ```bash
   python3 apollo_enrichment.py
   ```
5. **Dispatch Referral & Executive Emails with Attachments:**
   ```bash
   python3 outreach.py
   ```

---

## Database Management

All state, scraped listings, matching scores, tailored content, and outreach statuses are tracked inside **`jobs.db`** (`SQLite`).

### Status Pipeline Values:
- **`PENDING`**: Raw scraped job awaiting tailoring.
- **`TAILORED`**: AI evaluation completed, tailored resume and cover letter generated.
- **`APPLIED`**: Job submission completed via automation.
- **`SENT`**: Outreach email with attached PDF successfully dispatched.
- **`SKIPPED` / `FAILED`**: Missing descriptions or execution issues logged for review.

To reset job statuses or inspect records:
```bash
sqlite3 jobs.db "SELECT title, company, status, match_score FROM jobs;"
```

---

## Security & Best Practices

- **Never Commit Secrets:** Do not commit `.env`, `jobs.db`, or `resume.pdf` to version control.
- **Email Sending Limits:** Keep outreach daily volume within recommended SMTP service limits (e.g., max 50–100 emails/day for standard Gmail SMTP) to maintain domain reputation.