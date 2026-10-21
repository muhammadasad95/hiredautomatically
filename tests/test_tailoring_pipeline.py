import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import claude_engine
from resume_documents import parse_tailored_resume_document


class TailoringWorkflowTests(unittest.TestCase):
    SOURCE = """Jordan Example
jordan@example.test

PROFILE
Principal Engineer with 12 years building identity systems.

EXPERIENCE
Example Corp | 2020-Present
- Reduced provisioning time by 40% through workflow automation.
"""

    def _claude_response(self, data):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(data))])

    def test_score_rewrite_stress_test_share_conversation_and_store_complete_resume(self):
        lines = self.SOURCE.splitlines()
        claim = "- Reduced provisioning time by 40% through workflow automation."
        claim_line = next(i for i, line in enumerate(lines, start=1) if line == claim)
        stage_results = [{
            "match_score": 82,
            "top_five_missing_keywords": ["OIDC", "React"],
            "red_flags": ["15-year requirement exceeds stated 12 years"],
            "final_resume_text": self.SOURCE,
            "final_experience_evidence": [{"claim": claim, "source_lines": [claim_line]}],
            "ats_review": {
                "sections_likely_skipped": ["Profile can be made more scannable"],
                "hiring_manager_concerns": ["Requested tenure is higher than stated experience"],
                "changes_made": ["Clarified profile and retained the tenure gap"],
                "remaining_gaps": ["No claim of 15 years is made"],
            },
            "cover_letter": "I am applying to the Principal Engineer role at Pearson. My identity platform experience is relevant.",
        }]
        calls = []

        def fake_create(**kwargs):
            calls.append({**kwargs, "messages": list(kwargs["messages"])})
            return self._claude_response(stage_results[len(calls) - 1])

        connection = sqlite3.connect(":memory:")
        connection.execute("""
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, title TEXT, company TEXT, description TEXT,
                status TEXT, match_score INTEGER, missing_keywords TEXT, red_flags TEXT,
                tailored_resume TEXT, cover_letter TEXT
            )
        """)
        connection.execute(
            "INSERT INTO jobs (id,title,company,description,status) VALUES (?,?,?,?,?)",
            ("job-1", "Principal Engineer", "Pearson", "Identity role description " * 10, "PENDING"),
        )
        cursor = connection.cursor()
        with patch.object(claude_engine, "MASTER_RESUME", self.SOURCE), \
             patch.object(claude_engine.client.messages, "create", side_effect=fake_create):
            claude_engine._process_pending_job(
                connection,
                cursor,
                ("job-1", "Principal Engineer", "Pearson", "Identity role description " * 10),
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]["messages"]), 1)
        self.assertIn("STEP 1", calls[0]["messages"][0]["content"])
        self.assertIn("STEP 2", calls[0]["messages"][0]["content"])
        self.assertIn("STEP 3", calls[0]["messages"][0]["content"])
        stored = connection.execute(
            "SELECT status,match_score,tailored_resume,cover_letter FROM jobs WHERE id='job-1'"
        ).fetchone()
        self.assertEqual(stored[0], "TAILORED")
        self.assertEqual(stored[1], 82)
        document = parse_tailored_resume_document(stored[2])
        self.assertEqual(document["schema_version"], 3)
        self.assertIn("EXPERIENCE", document["final_resume_text"])
        self.assertTrue(document["ats_review"]["remaining_gaps"])
        self.assertIn("Pearson", stored[3])
        connection.close()

    def test_numeric_claim_without_source_evidence_fails_validation(self):
        lines = self.SOURCE.splitlines()
        claim_line = next(i for i, line in enumerate(lines, start=1) if "Reduced provisioning" in line)
        with self.assertRaisesRegex(ValueError, "unsupported numeric claims"):
            claude_engine._validate_evidence_refs(
                [{"claim": "- Increased revenue by 900%.", "source_lines": [claim_line]}],
                self.SOURCE + "\n- Increased revenue by 900%.",
                self.SOURCE,
                "test evidence",
            )

    def test_json_parser_accepts_wrapped_or_fenced_objects_safely(self):
        examples = [
            ('Here is the JSON:\n{"value": "a } brace", "n": 1}\nDone.', {"value": "a } brace", "n": 1}),
            ('```json\n{"value": 2}\n```', {"value": 2}),
        ]
        for raw, expected in examples:
            with self.subTest(raw=raw):
                response = SimpleNamespace(content=[SimpleNamespace(type="text", text=raw)])
                self.assertEqual(claude_engine._parse_claude_result(response, require_score=False), expected)

    def test_response_parser_ignores_thinking_blocks(self):
        response = SimpleNamespace(content=[
            SimpleNamespace(type="thinking", thinking="internal reasoning"),
            SimpleNamespace(type="text", text='```json\n{"value": 3}\n```'),
        ])
        self.assertEqual(claude_engine._parse_claude_result(response, require_score=False), {"value": 3})


if __name__ == "__main__":
    unittest.main()
