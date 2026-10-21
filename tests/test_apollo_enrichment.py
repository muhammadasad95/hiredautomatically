import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import apollo_enrichment
from apollo_enrichment import register_verified_company_domain


class ApolloEnrichmentTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = handle.name
        handle.close()
        connection = sqlite3.connect(self.db_path)
        connection.executescript("""
            CREATE TABLE jobs (
                id TEXT PRIMARY KEY, title TEXT, company TEXT, description TEXT,
                location TEXT, job_url TEXT, status TEXT, match_score INTEGER,
                tailored_resume TEXT, cover_letter TEXT
            );
            INSERT INTO jobs VALUES (
                'job-1', 'IAM Engineer', 'Acme Incorporated', 'Role details', 'Remote',
                'https://jobs.example/1', 'TAILORED', 90, 'Resume for this job', 'Cover letter for this job'
            );
        """)
        connection.commit()
        connection.close()
        apollo_enrichment.init_contacts_db(self.db_path)

    def tearDown(self):
        os.unlink(self.db_path)

    def test_domain_registration_requires_source_and_domain_not_company_guess(self):
        with self.assertRaises(ValueError):
            register_verified_company_domain("Acme Incorporated", "acme incorporated.com", "", self.db_path)
        with self.assertRaises(ValueError):
            register_verified_company_domain("Acme Incorporated", "Acme Incorporated", "company name guessed", self.db_path)

    def test_enrichment_skips_company_without_registered_verified_domain(self):
        with patch.object(apollo_enrichment, "APOLLO_API_KEY", "test-key"), \
             patch.object(apollo_enrichment.requests, "post") as post:
            result = apollo_enrichment.enrich_company_contacts("Acme Incorporated", db_name=self.db_path)
        self.assertEqual(result, [])
        post.assert_not_called()

    def test_only_matching_organization_contacts_are_stored_and_linked_to_job(self):
        register_verified_company_domain(
            "Acme Incorporated", "acme.example", "Company careers page", self.db_path
        )
        response = Mock(status_code=200)
        response.json.return_value = {
            "people": [
                {
                    "id": "person-good", "email": "recruiter@acme.example",
                    "first_name": "Rae", "last_name": "Recruiter", "title": "Recruiter",
                    "organization": {"primary_domain": "acme.example"},
                },
                {
                    "id": "person-wrong", "email": "other@wrong.example",
                    "first_name": "Wrong", "last_name": "Org", "title": "CTO",
                    "organization": {"primary_domain": "wrong.example"},
                },
                {
                    "id": "person-unverified", "email": "unknown@acme.example",
                    "first_name": "Unknown", "last_name": "Org", "title": "Recruiter",
                    "organization": {},
                },
                {
                    "id": "person-email-mismatch", "email": "person@wrong.example",
                    "first_name": "Mismatch", "last_name": "Email", "title": "Recruiter",
                    "organization": {"primary_domain": "acme.example"},
                },
            ]
        }
        with patch.object(apollo_enrichment, "APOLLO_API_KEY", "test-key"), \
             patch.object(apollo_enrichment.requests, "post", return_value=response) as post:
            accepted = apollo_enrichment.enrich_company_contacts("Acme Incorporated", db_name=self.db_path)

        self.assertEqual([person["id"] for person in accepted], ["person-good"])
        self.assertEqual(post.call_args.kwargs["json"]["q_organization_domains"], "acme.example")
        connection = sqlite3.connect(self.db_path)
        contacts = connection.execute(
            "SELECT id, job_id, company_domain FROM contacts ORDER BY id"
        ).fetchall()
        self.assertEqual(contacts, [("person-good", "job-1", "acme.example")])
        connection.close()

    def test_supplied_domain_must_match_registered_value(self):
        register_verified_company_domain(
            "Acme Incorporated", "acme.example", "Company careers page", self.db_path
        )
        with patch.object(apollo_enrichment, "APOLLO_API_KEY", "test-key"), \
             patch.object(apollo_enrichment.requests, "post") as post:
            result = apollo_enrichment.enrich_company_contacts(
                "Acme Incorporated", verified_domain="impostor.example", db_name=self.db_path
            )
        self.assertEqual(result, [])
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
