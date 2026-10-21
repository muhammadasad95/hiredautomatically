import os
import json
import sqlite3
import smtplib
import tempfile
import anthropic
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from dotenv import load_dotenv
from pdf_generator import create_tailored_pdf
from outreach_safety import get_outreach_settings, select_unique_company_contacts

load_dotenv()

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MASTER_RESUME_PDF = os.getenv("MASTER_RESUME_PDF", "resume.pdf")
WORKSPACE_ID = os.getenv("ANTHROPIC_WORKSPACE_ID", "default")

DB_NAME = "jobs.db"

# Pass default headers for org-wide API keys requiring a workspace context
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

EMAIL_PROMPT = """
Write a concise, professional, high-converting outreach email (max 120 words) from a candidate reaching out to {company}.
Target Recipient: {first_name} ({title})

Guidelines:
- Reference the role/company naturally.
- Never invent candidate accomplishments, numbers, credentials, or experience.
- No candidate resume evidence is provided to this prompt, so do not claim a specific accomplishment or metric.
- Say the resume is attached and the cover letter is included below; do not claim the cover letter is attached.
- End with a low-friction call-to-action asking for a brief 10-minute chat or referral.

Return raw JSON with keys: "subject", "body".
"""

def generate_email_content(company, first_name, title):
    prompt = EMAIL_PROMPT.format(company=company, first_name=first_name, title=title)
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = response.content[0].text.strip()
    if raw.startswith("```json"):
        raw = raw[7:-3].strip()
    elif raw.startswith("```"):
        raw = raw[3:-3].strip()
    return json.loads(raw)

def send_smtp_email_with_attachments(to_email, subject, body, pdf_path=None, cover_letter_text=None):
    msg = MIMEMultipart()
    msg['From'] = SMTP_EMAIL
    msg['To'] = to_email
    msg['Subject'] = subject

    # Main Body Text
    full_body = body
    if cover_letter_text:
        full_body += f"\n\n--- COVER LETTER ---\n\n{cover_letter_text}"

    msg.attach(MIMEText(full_body, 'plain'))

    # Attach PDF Resume if available
    if pdf_path and os.path.exists(pdf_path):
        with open(pdf_path, 'rb') as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_path)}"'
            msg.attach(part)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)

def _init_outreach_safety_tables(cursor):
    cursor.execute("""
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
    """)
    contact_columns = {row[1] for row in cursor.execute("PRAGMA table_info(contacts)").fetchall()}
    for name in ("job_id", "company_domain"):
        if name not in contact_columns:
            cursor.execute(f"ALTER TABLE contacts ADD COLUMN {name} TEXT")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS outreach_suppression (
            email TEXT PRIMARY KEY COLLATE NOCASE,
            reason TEXT NOT NULL DEFAULT 'OPT_OUT',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS outreach_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id TEXT NOT NULL,
            job_id TEXT,
            email TEXT NOT NULL,
            company TEXT NOT NULL,
            subject TEXT,
            body TEXT,
            state TEXT NOT NULL,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    event_columns = {row[1] for row in cursor.execute("PRAGMA table_info(outreach_events)").fetchall()}
    if "job_id" not in event_columns:
        cursor.execute("ALTER TABLE outreach_events ADD COLUMN job_id TEXT")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verified_company_domains (
            company_key TEXT PRIMARY KEY,
            company_name TEXT NOT NULL,
            domain TEXT NOT NULL,
            verification_source TEXT NOT NULL,
            verified_at TIMESTAMP NOT NULL
        )
    """)


def add_to_outreach_suppression(email, reason="OPT_OUT", db_name=DB_NAME):
    """Persistently suppress an address from future outreach campaigns."""
    normalized_email = (email or "").strip().lower()
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("A valid email address is required for suppression.")
    conn = sqlite3.connect(db_name)
    try:
        cursor = conn.cursor()
        _init_outreach_safety_tables(cursor)
        cursor.execute(
            "INSERT OR REPLACE INTO outreach_suppression (email, reason) VALUES (?, ?)",
            (normalized_email, reason),
        )
        conn.commit()
    finally:
        conn.close()


def _eligible_outreach_contacts(cursor, limit):
    cursor.execute("""
                SELECT c.id, c.company, c.first_name, c.title, c.email,
                             j.tailored_resume, j.cover_letter, j.id
        FROM contacts c
                JOIN jobs j ON j.id = c.job_id
                                     AND LOWER(TRIM(j.company)) = LOWER(TRIM(c.company))
                JOIN verified_company_domains v
                    ON LOWER(TRIM(v.company_name)) = LOWER(TRIM(c.company))
                 AND LOWER(v.domain) = LOWER(c.company_domain)
        WHERE c.status = 'NEW'
          AND c.email IS NOT NULL AND TRIM(c.email) != ''
                    AND j.tailored_resume IS NOT NULL AND TRIM(j.tailored_resume) != ''
                      AND j.cover_letter IS NOT NULL AND TRIM(j.cover_letter) != ''
                      AND INSTR(LOWER(j.cover_letter), LOWER(TRIM(j.company))) > 0
          AND NOT EXISTS (
              SELECT 1 FROM outreach_suppression s
              WHERE LOWER(TRIM(s.email)) = LOWER(TRIM(c.email))
          )
          AND NOT EXISTS (
              SELECT 1 FROM outreach_events e
                            WHERE e.state IN ('SENDING', 'SENT', 'UNCERTAIN')
                AND (e.contact_id = c.id OR LOWER(TRIM(e.email)) = LOWER(TRIM(c.email)))
          )
        ORDER BY LOWER(TRIM(c.company)), LOWER(TRIM(c.email)), c.id
    """)
    rows = cursor.fetchall()
    return select_unique_company_contacts(rows, limit), len(rows)


def _sent_today_count(cursor):
    cursor.execute("""
        SELECT COUNT(*) FROM outreach_events
        WHERE state IN ('SENDING', 'SENT', 'UNCERTAIN') AND date(created_at) = date('now')
    """)
    return cursor.fetchone()[0]


def _record_outreach_event(cursor, conn, contact_id, job_id, email, company, subject, body, state, detail=None):
    cursor.execute("""
        INSERT INTO outreach_events (contact_id, job_id, email, company, subject, body, state, detail)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (contact_id, job_id, email, company, subject, body, state, detail))
    conn.commit()


def _process_outreach_contact(conn, cursor, contact, live_send, reserved_event_id=None):
    contact_id, company, first_name, title, email, tailored_resume, cover_letter, job_id = contact
    pdf_path = None
    try:
        content = generate_email_content(company, first_name, title)
        subject, body = content["subject"], content["body"]
        if not live_send:
            print(f"\n--- PREVIEW for {first_name} ({email}) at {company} ---\nSubject: {subject}\n\n{body}\n")
            _record_outreach_event(cursor, conn, contact_id, job_id, email, company, subject, body, "PREVIEW")
            return

        safe_company = "".join(char if char.isalnum() or char in "-_" else "_" for char in company)
        with tempfile.NamedTemporaryFile(prefix=f"Resume_{safe_company}_", suffix=".pdf", delete=False) as temp_pdf:
            pdf_path = temp_pdf.name
        create_tailored_pdf(tailored_resume, pdf_path, source_pdf_path=MASTER_RESUME_PDF)
        try:
            send_smtp_email_with_attachments(email, subject, body, pdf_path, cover_letter)
        except Exception as exc:
            # SMTP may fail after server acceptance; do not blindly retry.
            cursor.execute("UPDATE contacts SET status = 'SEND_UNCERTAIN' WHERE id = ?", (contact_id,))
            cursor.execute(
                "UPDATE outreach_events SET subject = ?, body = ?, state = 'UNCERTAIN', detail = ? WHERE id = ?",
                (subject, body, str(exc), reserved_event_id),
            )
            conn.commit()
            print(f"SMTP outcome uncertain for {email}; suppressing automatic retry.")
            return

        cursor.execute("UPDATE contacts SET status = 'SENT' WHERE id = ?", (contact_id,))
        cursor.execute(
            "UPDATE outreach_events SET subject = ?, body = ?, state = 'SENT' WHERE id = ?",
            (subject, body, reserved_event_id),
        )
        conn.commit()
        print(f"Sent outreach to {first_name} ({email}) at {company}.")
    except Exception as exc:
        print(f"Failed preparing outreach for {email}: {exc}")
        if reserved_event_id:
            cursor.execute(
                "UPDATE outreach_events SET state = 'FAILED', detail = ? WHERE id = ?",
                (str(exc), reserved_event_id),
            )
            cursor.execute("UPDATE contacts SET status = 'NEW' WHERE id = ? AND status = 'SENDING'", (contact_id,))
            conn.commit()
        else:
            _record_outreach_event(cursor, conn, contact_id, job_id, email, company, None, None, "FAILED", str(exc))
    finally:
        if pdf_path and os.path.exists(pdf_path):
            os.remove(pdf_path)


def dispatch_outreach_campaign(
    send_enabled=None,
    dry_run=None,
    max_per_run=None,
    max_per_day=None,
    db_name=DB_NAME,
):
    settings = get_outreach_settings(send_enabled, dry_run, max_per_run, max_per_day)
    live_send = settings["send_enabled"] and not settings["dry_run"]
    conn = sqlite3.connect(db_name)
    try:
        cursor = conn.cursor()
        _init_outreach_safety_tables(cursor)
        conn.commit()
        if live_send:
            # Serialize selection and reservations so concurrent invocations cannot
            # exceed the daily cap or send to the same contact twice.
            cursor.execute("BEGIN IMMEDIATE")
        candidates, eligible_count = _eligible_outreach_contacts(cursor, settings["max_per_run"])
        sent_today = _sent_today_count(cursor)
        if live_send:
            candidates = candidates[:max(0, settings["max_per_day"] - sent_today)]
            reserved = []
            for contact in candidates:
                contact_id, company, _first_name, _title, email = contact[:5]
                job_id = contact[7]
                cursor.execute("""
                    INSERT INTO outreach_events (contact_id, job_id, email, company, state)
                    VALUES (?, ?, ?, ?, 'SENDING')
                """, (contact_id, job_id, email, company))
                event_id = cursor.lastrowid
                cursor.execute("UPDATE contacts SET status = 'SENDING' WHERE id = ? AND status = 'NEW'", (contact_id,))
                if cursor.rowcount:
                    reserved.append((contact, event_id))
                else:
                    cursor.execute("DELETE FROM outreach_events WHERE id = ?", (event_id,))
            candidates = [contact for contact, _event_id in reserved]
            conn.commit()
        else:
            reserved = [(contact, None) for contact in candidates]

        mode = "LIVE SEND ENABLED" if live_send else "PREVIEW ONLY — NO EMAILS WILL BE SENT"
        print(
            f"Outreach mode: {mode}; selected {len(candidates)} of {eligible_count} eligible contacts "
            f"(run cap {settings['max_per_run']}, daily cap {settings['max_per_day']}, "
            f"already sent today {sent_today})."
        )
        for contact, event_id in reserved:
            _process_outreach_contact(conn, cursor, contact, live_send, event_id)
    finally:
        conn.close()

if __name__ == "__main__":
    dispatch_outreach_campaign()