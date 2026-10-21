import os
import json
import sqlite3
import smtplib
import anthropic
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from dotenv import load_dotenv
from pdf_generator import create_tailored_pdf

load_dotenv()

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
WORKSPACE_ID = os.getenv("ANTHROPIC_WORKSPACE_ID", "default")

DB_NAME = "jobs.db"

# Pass default headers for org-wide API keys requiring a workspace context
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

EMAIL_PROMPT = """
Write a concise, professional, high-converting outreach email (max 120 words) from a candidate reaching out to {company}.
Target Recipient: {first_name} ({title})

Guidelines:
- Reference the role/company naturally.
- State 1 key measurable accomplishment: "I recently built/scaled X resulting in Y."
- Mention that a tailored resume and cover letter are attached for quick review.
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

def dispatch_outreach_campaign():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Select pending contacts along with tailored job details
    query = """
        SELECT c.id, c.company, c.first_name, c.title, c.email, j.tailored_resume, j.cover_letter
        FROM contacts c
        LEFT JOIN jobs j ON LOWER(c.company) = LOWER(j.company)
        WHERE c.status = 'NEW'
    """
    cursor.execute(query)
    contacts = cursor.fetchall()

    for contact_id, company, first_name, title, email, tailored_resume, cover_letter in contacts:
        try:
            # Generate temporary PDF for this specific contact
            pdf_filename = f"Resume_{company.replace(' ', '_')}.pdf"
            pdf_path = create_tailored_pdf(tailored_resume or "Senior Software Engineer", pdf_filename)

            content = generate_email_content(company, first_name, title)
            
            send_smtp_email_with_attachments(
                to_email=email,
                subject=content['subject'],
                body=content['body'],
                pdf_path=pdf_path,
                cover_letter_text=cover_letter
            )
            
            cursor.execute("UPDATE contacts SET status = 'SENT' WHERE id = ?", (contact_id,))
            conn.commit()
            print(f"Dispatched email with PDF resume + Cover Letter to {first_name} ({email}) at {company}")

            # Clean up temporary PDF file after sending
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

        except Exception as e:
            print(f"Failed sending email to {email}: {e}")
            cursor.execute("UPDATE contacts SET status = 'FAILED' WHERE id = ?", (contact_id,))
            conn.commit()

    conn.close()

if __name__ == "__main__":
    dispatch_outreach_campaign()