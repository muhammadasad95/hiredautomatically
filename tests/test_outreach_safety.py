import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import outreach
import apollo_enrichment
from outreach_safety import get_outreach_settings, select_unique_company_contacts


class OutreachSafetyTests(unittest.TestCase):
    def test_defaults_are_preview_only_and_capped(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = get_outreach_settings()
        self.assertFalse(settings["send_enabled"])
        self.assertTrue(settings["dry_run"])
        self.assertEqual(settings["max_per_run"], 5)
        self.assertEqual(settings["max_per_day"], 5)

    def test_live_send_requires_two_explicit_settings(self):
        with patch.dict(os.environ, {"OUTREACH_SEND_ENABLED": "true", "OUTREACH_DRY_RUN": "false"}, clear=True):
            settings = get_outreach_settings()
        self.assertTrue(settings["send_enabled"])
        self.assertFalse(settings["dry_run"])

    def test_caps_reject_negative_or_invalid_environment(self):
        with patch.dict(os.environ, {"OUTREACH_MAX_PER_RUN": "-1"}, clear=True):
            with self.assertRaises(ValueError):
                get_outreach_settings()
        with patch.dict(os.environ, {"OUTREACH_MAX_PER_DAY": "many"}, clear=True):
            with self.assertRaises(ValueError):
                get_outreach_settings()

    def test_contact_selection_deduplicates_company_and_email(self):
        rows = [
            ("1", "Acme", "Alex", "Recruiter", "alex@acme.example", "resume", "letter"),
            ("2", " ACME ", "Blair", "CTO", "blair@acme.example", "resume", "letter"),
            ("3", "Other", "Casey", "Recruiter", "alex@acme.example", "resume", "letter"),
            ("4", "Other", "Dana", "Recruiter", "dana@other.example", "resume", "letter"),
        ]
        selected = select_unique_company_contacts(rows, limit=5)
        self.assertEqual([row[0] for row in selected], ["1", "4"])

    def test_zero_limit_selects_nothing(self):
        self.assertEqual(select_unique_company_contacts([("1", "Acme", "A", "R", "a@x")], 0), [])

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = handle.name
        handle.close()
        connection = sqlite3.connect(self.db_path)
        connection.executescript("""
            CREATE TABLE contacts (
                id TEXT PRIMARY KEY, company TEXT, first_name TEXT, last_name TEXT,
                title TEXT, email TEXT, status TEXT DEFAULT 'NEW', job_id TEXT,
                company_domain TEXT
            );
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, title TEXT, company TEXT, tailored_resume TEXT,
                cover_letter TEXT, match_score INTEGER
            );
            CREATE TABLE verified_company_domains (
                company_key TEXT PRIMARY KEY, company_name TEXT, domain TEXT,
                verification_source TEXT, verified_at TEXT
            );
            INSERT INTO jobs VALUES ('job-1', 'IAM Engineer', 'Acme', 'Verified resume text', 'Cover note for Acme.', 90);
            INSERT INTO contacts VALUES ('contact-1', 'Acme', 'Alex', 'One', 'Recruiter', 'alex@acme.example', 'NEW', 'job-1', 'acme.example');
            INSERT INTO contacts VALUES ('contact-2', 'Acme', 'Blair', 'Two', 'CTO', 'blair@acme.example', 'NEW', 'job-1', 'acme.example');
            INSERT INTO verified_company_domains VALUES ('acme', 'Acme', 'acme.example', 'test fixture', '2026-10-21T00:00:00+00:00');
        """)
        connection.commit()
        connection.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def test_preview_dispatch_never_calls_smtp_and_only_selects_one_company_contact(self):
        content = {"subject": "Role conversation", "body": "A concise, evidence-safe note."}
        with patch.object(outreach, "generate_email_content", return_value=content) as generate, \
             patch.object(outreach, "send_smtp_email_with_attachments") as smtp_send, \
             patch.dict(os.environ, {}, clear=True):
            outreach.dispatch_outreach_campaign(db_name=self.db_path)

        generate.assert_called_once()
        smtp_send.assert_not_called()
        connection = sqlite3.connect(self.db_path)
        self.assertEqual(connection.execute("SELECT status FROM contacts WHERE id='contact-1'").fetchone()[0], "NEW")
        self.assertEqual(connection.execute("SELECT status FROM contacts WHERE id='contact-2'").fetchone()[0], "NEW")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM outreach_events WHERE state='PREVIEW'").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT job_id FROM outreach_events WHERE state='PREVIEW'").fetchone()[0], "job-1")
        connection.close()

    def test_suppressed_address_is_not_previewed(self):
        outreach.add_to_outreach_suppression("alex@acme.example", db_name=self.db_path)
        with patch.object(
            outreach,
            "generate_email_content",
            return_value={"subject": "Test", "body": "Test body"},
        ) as generate:
            outreach.dispatch_outreach_campaign(db_name=self.db_path)
        generate.assert_called_once()
        self.assertEqual(generate.call_args.args[1], "Blair")

    def test_unlinked_legacy_contact_is_not_eligible(self):
        connection = sqlite3.connect(self.db_path)
        connection.execute("UPDATE contacts SET job_id = NULL WHERE id = 'contact-1'")
        connection.commit()
        connection.close()
        with patch.object(
            outreach,
            "generate_email_content",
            return_value={"subject": "Test", "body": "Test body"},
        ) as generate:
            outreach.dispatch_outreach_campaign(db_name=self.db_path)
        generate.assert_called_once()
        self.assertEqual(generate.call_args.args[1], "Blair")
        connection = sqlite3.connect(self.db_path)
        event_contact = connection.execute(
            "SELECT contact_id FROM outreach_events WHERE state='PREVIEW'"
        ).fetchone()[0]
        self.assertEqual(event_contact, "contact-2")
        connection.close()

    def test_uses_resume_from_exactly_linked_job(self):
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?)",
            ("job-higher-score", "Other role", "Acme", "Different resume", "Different cover for Acme.", 99),
        )
        connection.commit()
        connection.close()

        content = {"subject": "Role conversation", "body": "A concise note."}
        with patch.object(outreach, "generate_email_content", return_value=content), \
             patch.object(outreach, "create_tailored_pdf") as create_pdf, \
             patch.object(outreach, "send_smtp_email_with_attachments"):
            outreach.dispatch_outreach_campaign(
                send_enabled=True, dry_run=False, max_per_run=1, max_per_day=1, db_name=self.db_path
            )
        self.assertEqual(create_pdf.call_args.args[0], "Verified resume text")

    def test_explicit_live_send_is_bounded_and_records_smtp_acceptance(self):
        content = {"subject": "Role conversation", "body": "A concise, evidence-safe note."}
        with patch.object(outreach, "generate_email_content", return_value=content), \
             patch.object(outreach, "create_tailored_pdf"), \
             patch.object(outreach, "send_smtp_email_with_attachments") as smtp_send:
            outreach.dispatch_outreach_campaign(
                send_enabled=True,
                dry_run=False,
                max_per_run=5,
                max_per_day=1,
                db_name=self.db_path,
            )

        smtp_send.assert_called_once()
        connection = sqlite3.connect(self.db_path)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM outreach_events WHERE state='SENT'").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT job_id FROM outreach_events WHERE state='SENT'").fetchone()[0], "job-1")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM contacts WHERE status='SENT'").fetchone()[0], 1)
        connection.close()

    def test_ambiguous_smtp_failure_is_not_automatically_retried(self):
        content = {"subject": "Role conversation", "body": "A concise, evidence-safe note."}
        with patch.object(outreach, "generate_email_content", return_value=content), \
             patch.object(outreach, "create_tailored_pdf"), \
             patch.object(outreach, "send_smtp_email_with_attachments", side_effect=OSError("connection lost")):
            outreach.dispatch_outreach_campaign(
                send_enabled=True,
                dry_run=False,
                max_per_run=5,
                max_per_day=1,
                db_name=self.db_path,
            )

        connection = sqlite3.connect(self.db_path)
        self.assertEqual(connection.execute("SELECT status FROM contacts WHERE id='contact-1'").fetchone()[0], "SEND_UNCERTAIN")
        self.assertEqual(connection.execute("SELECT state FROM outreach_events").fetchone()[0], "UNCERTAIN")
        connection.close()


if __name__ == "__main__":
    unittest.main()