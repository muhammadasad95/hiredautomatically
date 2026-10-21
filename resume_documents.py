"""Build resume documents from preserved source text and validated excerpts."""

from __future__ import annotations

import json
import re
from typing import Any

_SOURCE_REQUIRED = "Source resume text is required."
_TARGET_ROLE_REQUIRED = "Target role is required."
_NUMBER_PATTERN = r"\b\d+(?:[.,]\d+)?%?\b"


def _normalize_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _as_nonempty_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings.")
    cleaned = [item.strip() for item in value if item.strip()]
    if len(cleaned) > 12:
        raise ValueError(f"{field_name} may contain at most 12 entries.")
    return cleaned


def build_tailored_resume_document(
    source_resume_text: str,
    target_role: str,
    targeted_summary: Any,
    highlighted_skills: Any,
) -> str:
    """Serialize a complete source resume plus fact-checked emphasis excerpts.

    The original resume text is stored verbatim. AI-generated summary/highlight
    strings are accepted only when they are exact excerpts (ignoring whitespace
    and case) from the source, preventing invented candidate statements.
    """
    if not isinstance(source_resume_text, str) or not source_resume_text.strip():
        raise ValueError(_SOURCE_REQUIRED)
    if not isinstance(target_role, str) or not target_role.strip():
        raise ValueError(_TARGET_ROLE_REQUIRED)

    source_normalized = _normalize_text(source_resume_text)
    summaries = _as_nonempty_string_list(targeted_summary, "targeted_summary")
    skills = _as_nonempty_string_list(highlighted_skills, "highlighted_skills")

    for excerpt in summaries + skills:
        if _normalize_text(excerpt) not in source_normalized:
            raise ValueError("Resume emphasis must be copied from the source resume; unsupported excerpt rejected.")

    document = {
        "schema_version": 1,
        "target_role": target_role.strip(),
        "targeted_summary": summaries,
        "highlighted_skills": skills,
        "source_resume_text": source_resume_text,
    }
    return json.dumps(document, ensure_ascii=False)


def number_resume_lines(source_resume_text: str) -> str:
    """Return a line-numbered view for model selection, preserving source lines."""
    if not isinstance(source_resume_text, str) or not source_resume_text.strip():
        raise ValueError(_SOURCE_REQUIRED)
    return "\n".join(
        f"{line_number}: {line}"
        for line_number, line in enumerate(source_resume_text.splitlines(), start=1)
    )


def build_tailored_resume_from_line_refs(
    source_resume_text: str,
    target_role: str,
    targeted_summary_lines: Any,
    highlighted_skill_lines: Any,
) -> str:
    """Construct highlights exclusively from validated source line numbers."""
    if not isinstance(source_resume_text, str) or not source_resume_text.strip():
        raise ValueError(_SOURCE_REQUIRED)
    if not isinstance(target_role, str) or not target_role.strip():
        raise ValueError(_TARGET_ROLE_REQUIRED)

    source_lines = source_resume_text.splitlines()
    summary_refs = _validate_line_refs(targeted_summary_lines, "targeted_summary_lines", len(source_lines), 5)
    skill_refs = _validate_line_refs(highlighted_skill_lines, "highlighted_skill_lines", len(source_lines), 12)
    if any(not source_lines[index - 1].strip() for index in summary_refs + skill_refs):
        raise ValueError("Selected source lines cannot be blank.")
    summary, skills = _derive_summary_and_skills(source_lines, summary_refs, skill_refs)

    document = {
        "schema_version": 2,
        "target_role": target_role.strip(),
        "targeted_summary": summary,
        "highlighted_skills": skills,
        "source_resume_text": source_resume_text,
        "targeted_summary_lines": summary_refs,
        "highlighted_skill_lines": skill_refs,
    }
    return json.dumps(document, ensure_ascii=False)


def build_ats_tailored_resume_document(
    source_resume_text: str,
    target_role: str,
    target_company: str,
    final_resume_text: Any,
    evidence_refs: Any,
    match_score: Any,
    missing_keywords: Any,
    red_flags: Any,
    ats_review: Any,
) -> str:
    """Create a full rewritten résumé with citations back to source lines."""
    source_lines = _validate_full_resume_inputs(
        source_resume_text, final_resume_text, target_role, target_company, match_score, ats_review
    )
    keywords = _as_nonempty_string_list(missing_keywords, "missing_keywords")
    flags = _as_nonempty_string_list(red_flags, "red_flags")
    validated_evidence = _validate_full_resume_evidence(evidence_refs, final_resume_text, source_lines)
    _validate_resume_numbers(final_resume_text, source_resume_text)

    document = {
        "schema_version": 3,
        "target_role": target_role.strip(),
        "target_company": target_company.strip(),
        "match_score": match_score,
        "missing_keywords": keywords,
        "red_flags": flags,
        "source_resume_text": source_resume_text,
        "final_resume_text": final_resume_text.strip(),
        "evidence_refs": validated_evidence,
        "ats_review": ats_review,
    }
    return json.dumps(document, ensure_ascii=False)


def _validate_full_resume_inputs(source_text, final_text, target_role, target_company, score, ats_review):
    if not isinstance(source_text, str) or not source_text.strip():
        raise ValueError(_SOURCE_REQUIRED)
    if not isinstance(final_text, str) or len(final_text.strip()) < 200:
        raise ValueError("Final tailored résumé is missing or incomplete.")
    if not isinstance(target_role, str) or not target_role.strip():
        raise ValueError(_TARGET_ROLE_REQUIRED)
    if not isinstance(target_company, str) or not target_company.strip():
        raise ValueError("Target company is required.")
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
        raise ValueError("Match score must be between 0 and 100.")
    if not isinstance(ats_review, dict):
        raise ValueError("ATS stress-test report is required.")

    _validate_preserved_identity_and_dates(source_text, final_text)
    return source_text.splitlines()


def _validate_preserved_identity_and_dates(source_text, final_text):
    normalized_final = _normalize_text(final_text)
    candidate_name = extract_candidate_name(source_text)
    if candidate_name and _normalize_text(candidate_name) not in normalized_final:
        raise ValueError("Final résumé dropped the source candidate name.")
    source_email = _extract_email(source_text)
    if source_email and source_email.casefold() not in final_text.casefold():
        raise ValueError("Final résumé dropped the source email address.")
    source_years = set(re.findall(r"\b(?:19|20)\d{2}\b", source_text))
    final_years = set(re.findall(r"\b(?:19|20)\d{2}\b", final_text))
    missing_years = source_years - final_years
    if missing_years:
        raise ValueError(f"Final résumé dropped source dates: {', '.join(sorted(missing_years))}.")


def _validate_full_resume_evidence(evidence_refs, final_text, source_lines):
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise ValueError("Each rewritten experience section needs source evidence references.")
    final_normalized = _normalize_text(final_text)
    unique_claims = {}
    for index, evidence in enumerate(evidence_refs, start=1):
        if not isinstance(evidence, dict):
            raise ValueError(f"Evidence reference {index} must be an object.")
        claim = evidence.get("claim")
        if not isinstance(claim, str) or _normalize_text(claim) not in final_normalized:
            raise ValueError(f"Evidence reference {index} does not match the final résumé.")
        refs = _validate_line_refs(evidence.get("source_lines"), f"evidence_refs[{index}].source_lines", len(source_lines), 50)
        if not refs or any(not source_lines[line - 1].strip() for line in refs):
            raise ValueError(f"Evidence reference {index} must cite nonblank source lines.")
        _validate_cited_claim_numbers(claim, refs, source_lines, index)
        unique_claims[_normalize_text(claim)] = {"claim": claim.strip(), "source_lines": refs}
    return list(unique_claims.values())


def _validate_cited_claim_numbers(claim, refs, source_lines, index):
    cited_source = " ".join(source_lines[line - 1] for line in refs)
    claim_numbers = set(re.findall(_NUMBER_PATTERN, claim))
    source_numbers = set(re.findall(_NUMBER_PATTERN, cited_source))
    if claim_numbers - source_numbers:
        raise ValueError(f"Evidence reference {index} adds unsupported numeric claims.")


def _validate_resume_numbers(final_text, source_text):
    for token in re.findall(_NUMBER_PATTERN, final_text):
        if token not in source_text:
            raise ValueError(f"Final résumé includes numeric claim {token!r} absent from the source resume.")


def _extract_email(text: str) -> str | None:
    for token in text.split():
        candidate = token.strip("<>()[]{};,\"'")
        if candidate.count("@") == 1 and "." in candidate.rsplit("@", 1)[1]:
            return candidate
    return None


def _validate_line_refs(value: Any, field_name: str, line_count: int, maximum: int) -> list[int]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{field_name} must be a list of at most {maximum} line numbers.")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ValueError(f"{field_name} entries must be integer line numbers.")
    if len(set(value)) != len(value):
        raise ValueError(f"{field_name} cannot contain duplicate line numbers.")
    if any(item < 1 or item > line_count for item in value):
        raise ValueError(f"{field_name} contains a line number outside the source resume.")
    return value


def _source_paragraphs(source_lines: list[str]):
    paragraphs = []
    current = []
    for line_number, raw_line in enumerate(source_lines, start=1):
        line = raw_line.strip()
        is_heading = line.isupper() and re.search(r"[A-Z]", line)
        is_bullet = line.startswith(("-", "•", "*"))
        if not line or is_heading or is_bullet:
            if current:
                paragraphs.append(current)
                current = []
            if is_bullet:
                paragraphs.append([(line_number, line)])
        else:
            current.append((line_number, line))
    if current:
        paragraphs.append(current)
    return paragraphs


def _sentences_for_selected_lines(source_lines: list[str], selected_lines: set[int]):
    sentences = []
    for paragraph in _source_paragraphs(source_lines):
        joined = " ".join(text for _, text in paragraph)
        boundaries = []
        position = 0
        for line_number, text in paragraph:
            boundaries.append((position, position + len(text), line_number))
            position += len(text) + 1
        for match in re.finditer(r"[^.!?]+[.!?](?=\s|$)", joined):
            overlaps_selected_line = any(
                line_number in selected_lines
                for start, end, line_number in boundaries
                if start < match.end() and end > match.start()
            )
            sentence = match.group().strip()
            if overlaps_selected_line and 35 <= len(sentence) <= 260:
                sentences.append(sentence)
    return sentences


def _skill_phrases_from_line(line: str):
    for phrase in re.split(r"[·•|;,]", line.strip()):
        phrase = phrase.strip(" \t-•|;:,.()\u00b7")
        if 2 <= len(phrase) <= 72:
            yield phrase


def _derive_summary_and_skills(source_lines: list[str], summary_refs: list[int], skill_refs: list[int]):
    summary = []
    seen_summary = set()
    for sentence in _sentences_for_selected_lines(source_lines, set(summary_refs)):
        normalized = _normalize_text(sentence)
        if normalized not in seen_summary:
            summary.append(sentence)
            seen_summary.add(normalized)
        if len(summary) >= 2:
            break

    skills = []
    seen_skills = set()
    for line_number in skill_refs:
        for phrase in _skill_phrases_from_line(source_lines[line_number - 1]):
            normalized = _normalize_text(phrase)
            if normalized not in seen_skills:
                skills.append(phrase)
                seen_skills.add(normalized)
            if len(skills) >= 8:
                return summary, skills
    return summary, skills


def _valid_document_fields(document: dict[str, Any]) -> bool:
    expected_types = {
        "target_role": str,
        "targeted_summary": list,
        "highlighted_skills": list,
        "source_resume_text": str,
    }
    return all(isinstance(document.get(key), expected) for key, expected in expected_types.items())


def _valid_v2_line_references(document: dict[str, Any]) -> bool:
    source_lines = document["source_resume_text"].splitlines()
    try:
        summary_refs = _validate_line_refs(
            document.get("targeted_summary_lines"), "targeted_summary_lines", len(source_lines), 5
        )
        skill_refs = _validate_line_refs(
            document.get("highlighted_skill_lines"), "highlighted_skill_lines", len(source_lines), 12
        )
    except ValueError:
        return False

    refs = summary_refs + skill_refs
    if any(not source_lines[index - 1].strip() for index in refs):
        return False
    expected_summary, expected_skills = _derive_summary_and_skills(source_lines, summary_refs, skill_refs)
    legacy_summary = [source_lines[index - 1].strip() for index in summary_refs]
    legacy_skills = [source_lines[index - 1].strip() for index in skill_refs]
    return (
        (expected_summary == document["targeted_summary"] or legacy_summary == document["targeted_summary"])
        and (expected_skills == document["highlighted_skills"] or legacy_skills == document["highlighted_skills"])
    )


def parse_tailored_resume_document(value: str) -> dict[str, Any] | None:
    """Return a validated structured document, or None for legacy plain text."""
    try:
        document = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict) or document.get("schema_version") not in {1, 2, 3}:
        return None
    if document.get("schema_version") == 3:
        try:
            validated = build_ats_tailored_resume_document(
                source_resume_text=document.get("source_resume_text"),
                target_role=document.get("target_role"),
                target_company=document.get("target_company"),
                final_resume_text=document.get("final_resume_text"),
                evidence_refs=document.get("evidence_refs"),
                match_score=document.get("match_score"),
                missing_keywords=document.get("missing_keywords"),
                red_flags=document.get("red_flags"),
                ats_review=document.get("ats_review"),
            )
            return json.loads(validated)
        except (ValueError, TypeError):
            return None
    if not _valid_document_fields(document):
        return None
    if not document["source_resume_text"].strip():
        return None
    source_normalized = _normalize_text(document["source_resume_text"])
    excerpts = document["targeted_summary"] + document["highlighted_skills"]
    if any(not isinstance(item, str) or _normalize_text(item) not in source_normalized for item in excerpts):
        return None
    if document.get("schema_version") == 2:
        if not _valid_v2_line_references(document):
            return None
        source_lines = document["source_resume_text"].splitlines()
        document["targeted_summary"], document["highlighted_skills"] = _derive_summary_and_skills(
            source_lines,
            document["targeted_summary_lines"],
            document["highlighted_skill_lines"],
        )
    return document


def extract_candidate_name(source_resume_text: str) -> str:
    """Use the first nonempty source-resume line as the candidate name."""
    for line in source_resume_text.splitlines():
        candidate = line.strip()
        if candidate:
            return candidate
    return ""


def source_sections(source_resume_text: str) -> list[tuple[str, list[str]]]:
    """Split source text at likely headings without discarding any nonblank lines."""
    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_lines: list[str] = []
    for line in source_resume_text.splitlines():
        stripped = line.strip()
        if stripped and len(stripped) <= 64 and stripped.isupper() and re.search(r"[A-Z]", stripped):
            if current_heading or current_lines:
                sections.append((current_heading, current_lines))
            current_heading = stripped
            current_lines = []
        else:
            current_lines.append(line)
    if current_heading or current_lines:
        sections.append((current_heading, current_lines))
    return sections
