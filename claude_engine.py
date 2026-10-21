import os
import json
import sqlite3
import anthropic
import pypdf
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
DB_NAME = "jobs.db"
RESUME_PDF_PATH = "resume.pdf"

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

def load_resume_from_pdf(pdf_path):
    """Extracts plain text from the resume.pdf file located at root."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"Resume file '{pdf_path}' not found in root directory. Please add 'resume.pdf'.")
    
    reader = pypdf.PdfReader(pdf_path)
    extracted_text = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            extracted_text.append(text)
    
    full_resume_text = "\n".join(extracted_text)
    if not full_resume_text.strip():
        raise ValueError(f"Could not extract any readable text from '{pdf_path}'. Ensure it is not an image-only PDF.")
    
    return full_resume_text

# Automatically read text from resume.pdf at root
MASTER_RESUME = load_resume_from_pdf(RESUME_PDF_PATH)

PROMPT_TEMPLATE = """
You are a Senior Executive Recruiter and ATS Optimization Expert.
Analyze the provided master resume against the target job description.

Master Resume:
{master_resume}

Job Description:
{job_description}

Perform the following 3-step evaluation and output ONLY a raw JSON object with no Markdown formatting or intro text:
{{
  "match_score": <number 0-100>,
  "missing_keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
  "red_flags": ["flag1", "flag2", "flag3"],
  "tailored_experience": "Rewritten experience bullets using Google XYZ formula (Accomplished X, measured by Y, by doing Z), naturally incorporating missing keywords."
}}
"""

def process_pending_jobs():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, title, company, description FROM jobs WHERE status = 'PENDING'")
    pending_jobs = cursor.fetchall()
    
    print(f"Processing {len(pending_jobs)} pending jobs with Claude...")
    
    for job_id, title, company, description in pending_jobs:
        if not description or len(description) < 50:
            cursor.execute("UPDATE jobs SET status = 'SKIPPED' WHERE id = ?", (job_id,))
            continue

        prompt = PROMPT_TEMPLATE.format(
            master_resume=MASTER_RESUME,
            job_description=description
        )

        try:
            response = client.messages.create(
                model="claude-3-7-sonnet-20250219",
                max_tokens=2500,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}]
            )
            
            raw_text = response.content[0].text.strip()
            # Clean potential markdown code blocks
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:-3].strip()
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:-3].strip()

            data = json.loads(raw_text)

            cursor.execute('''
                UPDATE jobs 
                SET match_score = ?, 
                    missing_keywords = ?, 
                    red_flags = ?, 
                    tailored_resume = ?, 
                    status = 'TAILORED' 
                WHERE id = ?
            ''', (
                data.get("match_score", 0),
                json.dumps(data.get("missing_keywords", [])),
                json.dumps(data.get("red_flags", [])),
                data.get("tailored_experience", ""),
                job_id
            ))
            conn.commit()
            print(f"Optimized application for {title} at {company} (Score: {data.get('match_score')})")

        except Exception as e:
            print(f"Failed to process job {job_id}: {e}")
            cursor.execute("UPDATE jobs SET status = 'FAILED' WHERE id = ?", (job_id,))
            conn.commit()

    conn.close()

if __name__ == "__main__":
    print(f"Successfully loaded '{RESUME_PDF_PATH}' ({len(MASTER_RESUME)} characters).")
    process_pending_jobs()