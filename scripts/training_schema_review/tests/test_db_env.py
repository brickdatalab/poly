import os
import sys
import unittest
from pathlib import Path

# Ensure `scripts/` is on sys.path so `import training_schema_review` works.
SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from training_schema_review import db


class TestDbEnv(unittest.TestCase):
    def setUp(self) -> None:
        self._old = os.environ.copy()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._old)

    def test_project_ref_parse(self) -> None:
        self.assertEqual(db._project_ref_from_supabase_url("https://abc123.supabase.co"), "abc123")
        self.assertEqual(db._project_ref_from_supabase_url("http://abc123.supabase.co/"), "abc123")

    def test_build_db_url_prefers_explicit(self) -> None:
        os.environ["SUPABASE_DB_URL"] = "postgresql://postgres@db.x.supabase.co:5432/postgres"
        os.environ["SUPABASE_DB_PASSWORD"] = "x"
        self.assertEqual(db.build_db_url(), os.environ["SUPABASE_DB_URL"])

    def test_build_db_url_from_supabase_url(self) -> None:
        os.environ.pop("SUPABASE_DB_URL", None)
        os.environ["SUPABASE_URL"] = "https://cxvntzszdkyggjjenefn.supabase.co"
        os.environ["SUPABASE_DB_PASSWORD"] = "x"
        url = db.build_db_url()
        self.assertIn("db.cxvntzszdkyggjjenefn.supabase.co", url)
        self.assertTrue(url.startswith("postgresql://"))


if __name__ == "__main__":
    unittest.main()
