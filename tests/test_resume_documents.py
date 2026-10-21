import json
import os
import tempfile
import unittest
import unicodedata

import pypdf
from fpdf import FPDF

from pdf_generator import create_tailored_pdf
from resume_documents import (
    build_tailored_resume_document,
    build_ats_tailored_resume_document,
    build_tailored_resume_from_line_refs,
    number_resume_lines,
    parse_tailored_resume_document,
)


class ResumeDocumentTests(unittest.TestCase):
    SOURCE = """Jordan Example
Senior Engineer | Identity Systems
jordan@example.test | +1 555 010 0200

PROFILE
Engineer with 12 years of experience building identity platforms.

CORE SKILLS
Identity governance · Access management · Python

EXPERIENCE
Principal Engineer — Example Corp | 2020–Present
- Reduced provisioning time by 40% through workflow automation.
- Led a team of 6 engineers.

EDUCATION
BSc Computer Science, Example University, 2010
"""

    def test_builder_keeps_complete_source_and_only_accepts_source_excerpts(self):
        summary = ["Engineer with 12 years of experience building identity platforms."]
        skills = ["Identity governance", "Python"]
        encoded = build_tailored_resume_document(
            self.SOURCE, "Remote IAM Engineer", summary, skills
        )
        document = json.loads(encoded)
        self.assertEqual(document["source_resume_text"], self.SOURCE)
        self.assertEqual(document["target_role"], "Remote IAM Engineer")
        self.assertEqual(document["targeted_summary"], summary)
        self.assertEqual(document["highlighted_skills"], skills)

    def test_builder_rejects_unsupported_summary_or_skill_claim(self):
        with self.assertRaisesRegex(ValueError, "unsupported excerpt rejected"):
            build_tailored_resume_document(
                self.SOURCE,
                "IAM Engineer",
                ["Built a billion-dollar identity platform"],
                [],
            )
        with self.assertRaisesRegex(ValueError, "unsupported excerpt rejected"):
            build_tailored_resume_document(
                self.SOURCE,
                "IAM Engineer",
                [],
                ["Kubernetes expert"],
            )

    def test_parser_rejects_tampered_structured_document(self):
        encoded = build_tailored_resume_document(self.SOURCE, "IAM Engineer", [], [])
        self.assertIsNotNone(parse_tailored_resume_document(encoded))
        tampered = json.loads(encoded)
        tampered["highlighted_skills"] = ["Made-up certification"]
        self.assertIsNone(parse_tailored_resume_document(json.dumps(tampered)))

    def test_numbered_resume_uses_one_based_line_numbers(self):
        numbered = number_resume_lines("Name\n\nIdentity skill")
        self.assertEqual(numbered, "1: Name\n2: \n3: Identity skill")

    def test_line_reference_builder_extracts_only_selected_source_lines(self):
        encoded = build_tailored_resume_from_line_refs(
            self.SOURCE,
            "Remote IAM Engineer",
            targeted_summary_lines=[6, 13],
            highlighted_skill_lines=[9],
        )
        document = json.loads(encoded)
        source_lines = self.SOURCE.splitlines()
        self.assertEqual(document["schema_version"], 2)
        self.assertGreater(len(document["targeted_summary"]), 0)
        self.assertTrue(all(item in " ".join(source_lines) for item in document["targeted_summary"]))
        self.assertTrue(all(item in " ".join(source_lines) for item in document["highlighted_skills"]))
        self.assertTrue(all(len(item) <= 220 for item in document["targeted_summary"]))
        self.assertTrue(all(len(item) <= 72 for item in document["highlighted_skills"]))
        self.assertEqual(document["source_resume_text"], self.SOURCE)
        self.assertIsNotNone(parse_tailored_resume_document(encoded))

    def test_line_reference_builder_rejects_invalid_references(self):
        invalid_inputs = [
            {"targeted_summary_lines": [0], "highlighted_skill_lines": []},
            {"targeted_summary_lines": [999], "highlighted_skill_lines": []},
            {"targeted_summary_lines": [6, 6], "highlighted_skill_lines": []},
            {"targeted_summary_lines": [4], "highlighted_skill_lines": []},
            {"targeted_summary_lines": [True], "highlighted_skill_lines": []},
        ]
        for refs in invalid_inputs:
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                build_tailored_resume_from_line_refs(
                    self.SOURCE,
                    "Remote IAM Engineer",
                    **refs,
                )

    def test_parser_rejects_tampered_line_reference_claim(self):
        encoded = build_tailored_resume_from_line_refs(
            self.SOURCE, "Remote IAM Engineer", [6], [9]
        )
        document = json.loads(encoded)
        document["targeted_summary"][0] = "Invented achievement with 900% growth"
        self.assertIsNone(parse_tailored_resume_document(json.dumps(document)))

    def test_summary_reconstructs_a_complete_sentence_across_wrapped_lines(self):
        source = (
            "Jordan Example\nPROFILE\n"
            "Principal Engineer builds secure systems specialising in\n"
            "identity and access management.\n\n"
            "CORE SKILLS\nIdentity · SSO"
        )
        encoded = build_tailored_resume_from_line_refs(
            source,
            "Identity Engineer",
            targeted_summary_lines=[4],
            highlighted_skill_lines=[7],
        )
        document = json.loads(encoded)
        self.assertEqual(
            document["targeted_summary"],
            ["Principal Engineer builds secure systems specialising in identity and access management."],
        )

    def test_generated_pdf_contains_highlights_and_complete_source_unicode(self):
        encoded = build_tailored_resume_document(
            self.SOURCE,
            "Remote IAM Engineer",
            ["Engineer with 12 years of experience building identity platforms."],
            ["Identity governance", "Python"],
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as output:
            output_path = output.name
        try:
            create_tailored_pdf(encoded, output_path)
            reader = pypdf.PdfReader(output_path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        finally:
            os.unlink(output_path)

        for expected in (
            "Remote IAM Engineer",
            "Jordan Example",
            "jordan@example.test",
            "PROFILE",
            "CORE SKILLS",
            "Identity governance",
            "Principal Engineer",
            "Reduced provisioning time by 40%",
            "Led a team of 6 engineers",
            "EDUCATION",
            "2010",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)
        self.assertNotIn("Muhammad Asad", text)

    def test_legacy_text_pdf_does_not_inject_a_hard_coded_identity(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as output:
            output_path = output.name
        try:
            create_tailored_pdf("Generic legacy resume text", output_path)
            text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(output_path).pages)
        finally:
            os.unlink(output_path)
        self.assertIn("Generic legacy resume text", text)
        self.assertNotIn("Muhammad Asad", text)

    def test_legacy_tailoring_does_not_add_a_highlights_page_to_master_pdf(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as source_file:
            source_path = source_file.name
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as output_file:
            output_path = output_file.name
        try:
            original = FPDF()
            original.add_page()
            original.set_font("Helvetica", size=12)
            original.multi_cell(0, 8, "Original source resume page with full experience and factual details.")
            original.output(source_path)

            document = build_tailored_resume_document(
                self.SOURCE,
                "Remote IAM Engineer",
                ["Engineer with 12 years of experience building identity platforms."],
                ["Identity governance"],
            )
            create_tailored_pdf(document, output_path, source_pdf_path=source_path)
            pages = pypdf.PdfReader(output_path).pages
            source_pages = pypdf.PdfReader(source_path).pages
            self.assertEqual(len(pages), len(source_pages))
            self.assertEqual(pages[0].extract_text(), source_pages[0].extract_text())
            self.assertNotIn("Remote IAM Engineer", pages[0].extract_text())
        finally:
            os.unlink(source_path)
            os.unlink(output_path)

    def test_pdf_renderer_drops_nonportable_private_use_icon_glyphs(self):
        document = build_tailored_resume_document(
            "Jordan Example\nPROFILE\nIdentity\ue016platform\ue016engineering",
            "Identity Engineer",
            ["Identity\ue016platform\ue016engineering"],
            [],
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as output:
            output_path = output.name
        try:
            create_tailored_pdf(document, output_path)
            text = "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(output_path).pages)
        finally:
            os.unlink(output_path)
        self.assertIn("Identityplatformengineering", text)
        self.assertNotIn("\ue016", text)

    def _valid_full_resume_document(self, resume_text=None):
        source = resume_text or self.SOURCE
        source_lines = source.splitlines()
        bullet_line = next(
            index for index, line in enumerate(source_lines, start=1)
            if "Reduced provisioning time" in line
        )
        return build_ats_tailored_resume_document(
            source_resume_text=source,
            target_role="Remote IAM Engineer",
            target_company="Example Corp",
            final_resume_text=source,
            evidence_refs=[{
                "claim": "- Reduced provisioning time by 40% through workflow automation.",
                "source_lines": [bullet_line],
            }],
            match_score=82,
            missing_keywords=["OIDC"],
            red_flags=["No direct OIDC production experience stated"],
            ats_review={"sections_likely_skipped": [], "changes_made": ["Clarified bullets"]},
        )

    def test_full_tailored_document_preserves_identity_dates_and_ats_report(self):
        encoded = self._valid_full_resume_document()
        document = parse_tailored_resume_document(encoded)
        self.assertIsNotNone(document)
        self.assertEqual(document["schema_version"], 3)
        self.assertEqual(document["match_score"], 82)
        self.assertEqual(document["ats_review"]["changes_made"], ["Clarified bullets"])
        self.assertEqual(document["final_resume_text"], self.SOURCE.strip())

    def test_full_tailored_document_rejects_unsupported_numbers_and_lost_years(self):
        source_lines = self.SOURCE.splitlines()
        bullet_line = next(
            index for index, line in enumerate(source_lines, start=1)
            if "Reduced provisioning time" in line
        )
        for modified_text in (
            self.SOURCE.replace("40%", "400%"),
            self.SOURCE.replace("2020–Present", "2021–Present"),
        ):
            with self.subTest(modified=modified_text[:40]), self.assertRaises(ValueError):
                build_ats_tailored_resume_document(
                    source_resume_text=self.SOURCE,
                    target_role="Engineer",
                    target_company="Example Corp",
                    final_resume_text=modified_text,
                    evidence_refs=[{
                        "claim": "- Reduced provisioning time by 40% through workflow automation.",
                        "source_lines": [bullet_line],
                    }],
                    match_score=82,
                    missing_keywords=[],
                    red_flags=[],
                    ats_review={},
                )

    def test_schema_v3_pdf_renders_full_final_resume_without_appending_original(self):
        encoded = self._valid_full_resume_document()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as source_file:
            source_path = source_file.name
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as output_file:
            output_path = output_file.name
        try:
            source_pdf = FPDF()
            source_pdf.add_page()
            source_pdf.set_font("Helvetica", size=12)
            source_pdf.multi_cell(0, 8, "Master PDF should not be appended for schema v3.")
            source_pdf.output(source_path)
            create_tailored_pdf(encoded, output_path, source_pdf_path=source_path)
            output_text = "\n".join(
                page.extract_text() or "" for page in pypdf.PdfReader(output_path).pages
            )
        finally:
            os.unlink(source_path)
            os.unlink(output_path)
        for expected in (
            "Jordan Example",
            "Tailored for Remote IAM Engineer | Example Corp",
            "Reduced provisioning time by 40%",
            "EDUCATION",
        ):
            self.assertIn(expected, output_text)
        self.assertNotIn("Master PDF should not be appended", output_text)


if __name__ == "__main__":
    unittest.main()