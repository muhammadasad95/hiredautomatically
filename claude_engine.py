import os
import json
import sqlite3
import re
import math
import anthropic
import pypdf
from dotenv import load_dotenv
from job_priority import select_pending_jobs
from resume_documents import build_ats_tailored_resume_document, number_resume_lines

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

STEP1_PROMPT = """STEP 1 — SCORE IT
Act as a senior recruiter for this exact company. Analyze the candidate resume against the job description.
Target company: {company}
Target role: {title}

Return only JSON with:
{{"match_score": 0, "top_five_missing_keywords": [], "red_flags": [], "fit_rationale": ""}}
Provide a 0-100 match score, exactly five concise missing keywords (or fewer only if fewer are relevant), and three hiring-manager red flags visible quickly. Distinguish real experience gaps from presentation issues. Do not misrepresent a missing qualification as present."""

STEP2_PROMPT = """STEP 2 — REWRITE (same conversation)
Rewrite the COMPLETE resume, especially the experience section, for the target role. Use Google XYZ style where the source supports it: accomplished X, measured by Y, by doing Z. Naturally include relevant missing keywords only where the candidate's source supports the claim. Do not fabricate metrics, employers, dates, technologies, credentials, scope, or outcomes. Do not hide hard requirements gaps; frame them honestly. Preserve candidate identity/contact details, employers, job titles, chronology and dates.

Target company: {company}
Target role: {title}
Top missing keywords: {keywords}
Red flags from review: {red_flags}

Use the numbered source resume and exact job description already supplied earlier in this same conversation. Do not assume additional candidate facts.

Return only JSON:
{{"tailored_resume_text":"complete résumé with sections","experience_evidence":[{{"claim":"one rewritten experience bullet copied verbatim from tailored_resume_text","source_lines":[1,2]}}],"cover_letter":"concise, role-specific cover letter naming the target company"}}
Every newly written factual experience bullet must have a separate evidence object citing relevant 1-based source line numbers. Do not cite job-description lines as candidate experience."""

STEP3_PROMPT = """STEP 3 — STRESS-TEST (same conversation)
Act as both an ATS filter and a hiring manager scanning 200 resumes. Inspect the current tailored resume against the job description. Identify sections or facts likely to be skipped, buried, ambiguous, or weak; then rewrite those parts so they are clear, concise, ATS-readable, and compelling without inventing or overstating anything.

Keep all factual claims tied to the original source resume. Preserve the candidate's name/contact, employers, titles and all employment dates. Preserve numeric claims only if present in the original resume. Do not turn a missing keyword into an unsupported skill. Do not remove a genuine qualification gap; explicitly keep it in the review notes if material.

Return only JSON:
{{"ats_review":{{"sections_likely_skipped":[],"hiring_manager_concerns":[],"changes_made":[],"remaining_gaps":[]}},"final_resume_text":"complete revised résumé, not a summary page","final_experience_evidence":[{{"claim":"one final rewritten experience bullet copied verbatim from final_resume_text","source_lines":[1,2]}}]}}
Final experience evidence must cover each rewritten factual experience bullet. The final_resume_text must be the complete application-ready résumé."""

def _env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_claude_result(response, require_score=True):
    raw_text = _response_text(response)
    if not raw_text:
        raise ValueError("No text block returned in response.")

    try:
        data = json.loads(_extract_json_object(raw_text))
    except json.JSONDecodeError:
        cleaned_text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', raw_text)
        data = json.loads(_extract_json_object(cleaned_text))

    if not isinstance(data, dict):
        raise ValueError("Claude response must be a JSON object.")
    if require_score:
        score = data.get("match_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
            raise ValueError("Claude response must include a numeric match_score.")
        if not 0 <= score <= 100:
            raise ValueError("Claude match_score must be between 0 and 100.")
    return data


def _response_text(response):
    """Extract only text blocks; Anthropic extended-thinking responses also contain non-text blocks."""
    text_blocks = []
    for block in response.content:
        try:
            if getattr(block, "type", None) == "text":
                value = block.text
            else:
                value = None
        except (AttributeError, TypeError):
            value = None
        if isinstance(value, str) and value.strip():
            text_blocks.append(value.strip())
    if text_blocks:
        return "\n".join(text_blocks)
    # Fallback for SDK/test response objects without typed content blocks.
    try:
        value = response.text
    except (AttributeError, TypeError):
        value = None
    return value.strip() if isinstance(value, str) else ""


def _extract_json_object(raw_text):
    text = _strip_json_fences(raw_text.strip())
    start = text.find("{")
    if start < 0:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    end = _find_json_object_end(text, start)
    if end is None:
        raise json.JSONDecodeError("Unterminated JSON object", text, start)
    return text[start:end + 1]


def _strip_json_fences(text):
    if not text.startswith("```"):
        return text
    newline = text.find("\n")
    if newline >= 0:
        text = text[newline + 1:]
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3]
    return text.strip()


def _find_json_object_end(text, start):
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _request_json(messages, max_tokens=3500, require_score=True, stage="Claude stage"):
    response = client.messages.create(
        model="claude-sonnet-5-5",
        max_tokens=max_tokens,
        messages=messages,
    )
    try:
        data = _parse_claude_result(response, require_score=require_score)
    except Exception as exc:
        raise ValueError(f"{stage} returned invalid JSON/schema: {exc}") from exc
    return data, json.dumps(data, ensure_ascii=False)


def _validate_evidence_refs(evidence_refs, resume_text, source_text, label):
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise ValueError(f"{label} must cite source evidence for rewritten experience claims.")
    final_normalized = " ".join(resume_text.split()).casefold()
    source_lines = source_text.splitlines()
    validated = []
    for position, evidence in enumerate(evidence_refs, start=1):
        if not isinstance(evidence, dict):
            raise ValueError(f"{label} item {position} is not an object.")
        claim = evidence.get("claim")
        refs = evidence.get("source_lines")
        if not isinstance(claim, str) or " ".join(claim.split()).casefold() not in final_normalized:
            raise ValueError(f"{label} item {position} is not copied from the final résumé text.")
        if not isinstance(refs, list) or not refs or any(
            isinstance(ref, bool) or not isinstance(ref, int) or ref < 1 or ref > len(source_lines)
            for ref in refs
        ):
            raise ValueError(f"{label} item {position} has invalid source line references.")
        cited_source = " ".join(source_lines[ref - 1] for ref in refs)
        claim_numbers = set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", claim))
        if claim_numbers - set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", cited_source)):
            raise ValueError(f"{label} item {position} introduces unsupported numeric claims.")
        validated.append({"claim": claim.strip(), "source_lines": refs})
    return validated


def _generate_final_tailored_artifacts(title, company, description, match_score=None, missing_keywords=None, red_flags=None):
    """Run score, rewrite, and stress-test in one compact call; return final artifacts and score data."""
    cached_score = match_score is not None
    if cached_score:
        scoring = f"""STEP 1 — REUSE CACHED SCORE (do not call the score model again):
Company: {company}
Role: {title}
Match score: {match_score}/100
Top missing keywords: {json.dumps(missing_keywords or [], ensure_ascii=False)}
Red flags: {json.dumps(red_flags or [], ensure_ascii=False)}"""
        output_score_fields = ""
    else:
        scoring = f"""STEP 1 — SCORE IT:
Act as a senior recruiter for {company}, for the exact {title} role. Give a 0–100 match score, exactly five relevant missing keywords (fewer only when fewer apply), and three hiring-manager red flags. Be candid about hard gaps; do not claim absent qualifications."""
        output_score_fields = '"match_score":82,"top_five_missing_keywords":[],"red_flags":[], '

    prompt = f"""Perform these three steps sequentially and economically. Produce ONE final résumé only; do not output an intermediate rewritten résumé.

{scoring}

STEP 2 — REWRITE:
Rewrite the COMPLETE résumé, especially experience, using Google XYZ style only where source evidence supports it (accomplished X, measured by Y, by doing Z). Include relevant keywords only when supported. Do not invent metrics, employers, dates, technologies, credentials, scope, or outcomes. Preserve name, contact details, employers, titles, chronology and dates. Keep genuine qualification gaps honest.

STEP 3 — ATS/HIRING-MANAGER STRESS TEST:
Review the rewrite as an ATS filter and a hiring manager scanning 200 résumés. Identify skipped/buried/ambiguous sections and weak statements, then make those fixes directly in the single final résumé. Keep it complete and application-ready, not a summary or highlights sheet. Preserve every source employment year and candidate contact address. Every rewritten factual experience bullet needs line-number evidence from the numbered source résumé. Numeric claims must match the cited source lines exactly.

Numbered source résumé:
{number_resume_lines(MASTER_RESUME)}

Exact job description:
{description}

Return only compact JSON with keys:
{{{output_score_fields}"final_resume_text":"complete final résumé","final_experience_evidence":[{{"claim":"exact final experience bullet","source_lines":[1,2]}}],"ats_review":{{"sections_likely_skipped":[],"hiring_manager_concerns":[],"changes_made":[],"remaining_gaps":[]}},"cover_letter":"concise letter naming {company} and {title}, only supported facts, max 180 words"}}
Keep each ATS note brief. Do not include the source résumé again inside JSON."""
    data, _ = _request_json(
        [{"role": "user", "content": prompt}],
        max_tokens=5500,
        require_score=not cached_score,
        stage="Step 1 score + Step 2 rewrite + Step 3 stress-test",
    )
    if not cached_score:
        match_score = data["match_score"]
        missing_keywords = data.get("top_five_missing_keywords", [])
        red_flags = data.get("red_flags", [])
    missing_keywords = missing_keywords or []
    red_flags = red_flags or []
    final_resume = data.get("final_resume_text")
    evidence = _validate_evidence_refs(
        data.get("final_experience_evidence"), final_resume, MASTER_RESUME, "Final experience evidence"
    )
    ats_review = data.get("ats_review")
    if not isinstance(ats_review, dict):
        raise ValueError("Step 3 must return an ATS/hiring-manager stress-test report.")
    cover_letter = validate_regenerated_cover_letter({"cover_letter": data.get("cover_letter")}, company)
    tailored_resume = build_ats_tailored_resume_document(
        source_resume_text=MASTER_RESUME,
        target_role=title,
        target_company=company,
        final_resume_text=final_resume,
        evidence_refs=evidence,
        match_score=match_score,
        missing_keywords=missing_keywords,
        red_flags=red_flags,
        ats_review=ats_review,
    )
    return tailored_resume, cover_letter, match_score, missing_keywords, red_flags


def validate_cover_letter(data, target_company):
    """Reject missing or wrong-employer letters before persisting tailored data."""
    cover_letter = data.get("cover_letter") if isinstance(data, dict) else None
    if not isinstance(cover_letter, str) or not cover_letter.strip():
        raise ValueError("Claude response must include a non-empty cover letter.")
    if not isinstance(target_company, str) or not target_company.strip():
        raise ValueError("Target company is missing; cannot validate cover-letter recipient.")
    if target_company.strip().casefold() not in cover_letter.casefold():
        raise ValueError("Cover letter does not name the target hiring company; rejected.")
    return cover_letter


def validate_regenerated_cover_letter(data, target_company, max_words=180):
    cover_letter = validate_cover_letter(data, target_company)
    if len(cover_letter.split()) > max_words:
        raise ValueError(f"Generated cover letter exceeds {max_words} words; existing letter retained.")
    return cover_letter


def regenerate_cover_letter_for_job(job_id):
    """Regenerate and persist a correct cover letter for one TAILORED job only."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, company, description FROM jobs WHERE id = ? AND status = 'TAILORED'",
            (job_id,),
        )
        job = cursor.fetchone()
        if not job:
            raise ValueError("Job not found in TAILORED status; refusing cover-letter update.")

        _, title, company, description = job
        prompt = f"""Write a concise cover letter of at most 180 words for the actual target job below.

TARGET COMPANY (must be the employer addressed): {company}
TARGET ROLE: {title}

Use only claims supported by the candidate resume and the job description. Do not transfer a past employer/client name into the greeting or target-company reference. Do not invent metrics, dates, experience, technologies, or credentials. The letter must name the exact target company above and discuss this role.

Candidate resume (source of candidate facts):
{MASTER_RESUME}

Job description (source of role requirements):
{description}

Return only a JSON object with one key: "cover_letter". Include three concise body paragraphs with optional greeting and sign-off."""
        response = client.messages.create(
            model="claude-sonnet-5-5",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = _response_text(response)
        try:
            letter_data = json.loads(_extract_json_object(raw_text))
        except json.JSONDecodeError as exc:
            raise ValueError("Claude returned invalid cover-letter JSON; existing letter retained.") from exc

        cover_letter = validate_regenerated_cover_letter(letter_data, company)
        cursor.execute(
            "UPDATE jobs SET cover_letter = ? WHERE id = ? AND status = 'TAILORED'",
            (cover_letter, job_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Job changed during update; existing letter was not replaced.")
        conn.commit()
        return cover_letter
    finally:
        conn.close()


def _process_pending_job(conn, cursor, job):
    job_id, title, company, description = job[:4]
    if not description or len(description) < 50:
        cursor.execute("UPDATE jobs SET status = 'SKIPPED' WHERE id = ?", (job_id,))
        conn.commit()
        return

    try:
        tailored_resume, cover_letter, match_score, missing_keywords, red_flags = (
            _generate_final_tailored_artifacts(title, company, description)
        )
        if match_score < 50:
            cursor.execute(
                "UPDATE jobs SET status = 'DISCARDED', match_score = ? WHERE id = ?",
                (match_score, job_id),
            )
            conn.commit()
            print(f"Discarded job for {title} at {company} (Low Score: {match_score})")
            return

        cursor.execute(
            """UPDATE jobs
               SET match_score = ?, missing_keywords = ?, red_flags = ?,
                   tailored_resume = ?, cover_letter = ?, status = 'TAILORED'
               WHERE id = ?""",
            (
                match_score,
                json.dumps(missing_keywords),
                json.dumps(red_flags),
                tailored_resume,
                cover_letter,
                job_id,
            ),
        )
        print(f"Optimized application for {title} at {company} (Score: {match_score})")
        conn.commit()
    except Exception as exc:
        print(f"Failed to process job {job_id}: {exc}")
        cursor.execute("UPDATE jobs SET status = 'FAILED' WHERE id = ?", (job_id,))
        conn.commit()


def process_pending_jobs(limit=None, include_unknown=None):
    if limit is None:
        try:
            limit = int(os.getenv("TAILOR_BATCH_LIMIT", "10"))
        except ValueError as exc:
            raise ValueError("TAILOR_BATCH_LIMIT must be a non-negative integer") from exc
    if limit < 0:
        raise ValueError("limit must be zero or greater")
    if include_unknown is None:
        include_unknown = _env_bool("TAILOR_INCLUDE_UNKNOWN_WORK_MODE", default=False)

    conn = sqlite3.connect(DB_NAME)
    try:
        pending_jobs, unknown_count, eligible_count = select_pending_jobs(
            conn, limit=limit, include_unknown=include_unknown
        )
        print(
            f"Selected {len(pending_jobs)} of {eligible_count} eligible PENDING jobs "
            f"(batch limit {limit}); {unknown_count} unknown-work-mode jobs held for review. "
            "Priority: Remote IAM/identity, other remote, onsite/hybrid IAM/identity, "
            "other onsite/hybrid."
        )
        cursor = conn.cursor()
        for job in pending_jobs:
            _process_pending_job(conn, cursor, job)
    finally:
        conn.close()


def retry_failed_job(job_id):
    """Retry exactly one FAILED job by its database ID, with no queue reselection."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, company, description FROM jobs WHERE id = ? AND status = 'FAILED'",
            (job_id,),
        )
        job = cursor.fetchone()
        if not job:
            raise ValueError("The specified job does not exist with FAILED status.")
        cursor.execute("UPDATE jobs SET status = 'PENDING' WHERE id = ? AND status = 'FAILED'", (job_id,))
        conn.commit()
        _process_pending_job(conn, cursor, job)
    finally:
        conn.close()


def retailor_tailored_job(job_id):
    """Run Steps 2–3 for one tailored job using cached Step 1 results; one API call."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id,title,company,description,match_score,missing_keywords,red_flags
               FROM jobs WHERE id=? AND status='TAILORED'""",
            (job_id,),
        )
        job = cursor.fetchone()
        if not job:
            raise ValueError("The specified job does not exist in TAILORED status.")
        _, title, company, description, score, keywords_json, flags_json = job
        keywords = json.loads(keywords_json or "[]")
        flags = json.loads(flags_json or "[]")
        tailored_resume, cover_letter, _score, _keywords, _flags = _generate_final_tailored_artifacts(
            title, company, description, score, keywords, flags
        )
        cursor.execute(
            "UPDATE jobs SET tailored_resume=?,cover_letter=? WHERE id=? AND status='TAILORED'",
            (tailored_resume, cover_letter, job_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Job changed during retailoring; existing record was not replaced.")
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    print(f"Successfully loaded '{RESUME_PDF_PATH}' ({len(MASTER_RESUME)} characters).")
    process_pending_jobs()