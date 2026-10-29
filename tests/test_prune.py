"""Regression coverage for the ledger rebuild in tools/prune.py (stdlib only)."""
import contextlib
from datetime import datetime, timedelta
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools" / "prune.py"
spec = importlib.util.spec_from_file_location("prune", SCRIPT)
prune = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prune)
NOW = datetime(2026, 10, 30, 8, tzinfo=prune.HKT)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz)


def stamp(days_ago):
    return (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")


class PruneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.articles = self.repo / "articles"
        self.ledger = self.repo / "ledger.json"
        for target, value in (("ARTICLES_DIR", self.articles),
                              ("LEDGER_PATH", self.ledger),
                              ("datetime", FixedDateTime)):
            patcher = patch.object(prune, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_article(self, slug, days_ago, key=None):
        published_at = stamp(days_ago)
        aid = f"{published_at[:10]}-{slug}"
        path = self.articles / aid[:10] / f"{aid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "id": aid,
            "published_at": published_at,
            "story_key": key or slug,
            "en": {"headline": f"Headline for {slug}"},
        }), encoding="utf-8")
        return aid

    def run_prune(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["prune.py", *args]), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = prune.main()
        return status, stdout.getvalue(), stderr.getvalue()

    def covered(self):
        ledger = json.loads(self.ledger.read_text(encoding="utf-8"))
        self.assertEqual(set(ledger), {"covered", "updated_at"})
        return ledger["covered"]

    def test_damaged_ledgers_are_rebuilt_from_articles(self):
        recent = self.write_article("recent", 1)
        self.write_article("expired", 20)
        bare_list = json.dumps([{"key": "recent", "id": recent,
                                 "first_seen": stamp(1), "headline_en": "x"}])
        for content in ("PLACEHOLDER_FULL_LEDGER_WITH_APPEND\n// appended", "",
                        bare_list, '{"covered": "oops"}', "[1, null]"):
            with self.subTest(content=content[:30]):
                self.ledger.write_text(content, encoding="utf-8")
                self.assertEqual(self.run_prune()[0], 0)
                self.assertEqual([e["id"] for e in self.covered()], [recent])

    def test_missing_ledger_file_is_created(self):
        aid = self.write_article("story", 0)
        self.assertEqual(self.run_prune()[0], 0)
        self.assertEqual(self.covered(), [{
            "key": "story", "id": aid, "first_seen": stamp(0),
            "headline_en": "Headline for story",
        }])

    def test_existing_entries_win_and_stale_ones_are_trimmed(self):
        aid = self.write_article("story", 2, key="article-key")
        gap = self.write_article("gap", 1)
        self.ledger.write_text(json.dumps({"covered": [
            {"key": "old", "id": "2026-10-01-old", "first_seen": stamp(29)},
            {"key": "ledger-only", "id": "2026-10-29-never-written", "first_seen": stamp(1)},
            {"key": "hand-key", "id": aid, "first_seen": stamp(2)},
        ]}), encoding="utf-8")
        status, stdout, _ = self.run_prune()
        self.assertEqual(status, 0)
        self.assertIn("trimmed 1", stdout)
        self.assertIn("restored 1", stdout)
        covered = self.covered()
        self.assertEqual([e["id"] for e in covered], [aid, "2026-10-29-never-written", gap])
        self.assertEqual(covered[0]["key"], "hand-key")

    def test_unreadable_articles_are_skipped(self):
        aid = self.write_article("good", 0)
        bad = self.articles / aid[:10] / "broken.json"
        bad.write_text("{nope", encoding="utf-8")
        (self.articles / aid[:10] / "partial.json").write_text('{"id": "x"}', encoding="utf-8")
        self.assertEqual(self.run_prune()[0], 0)
        self.assertEqual([e["id"] for e in self.covered()], [aid])

    def test_dry_run_writes_nothing(self):
        self.write_article("story", 0)
        self.ledger.write_text("PLACEHOLDER", encoding="utf-8")
        status, stdout, _ = self.run_prune("--dry-run")
        self.assertEqual(status, 0)
        self.assertIn("[dry-run] restored 1", stdout)
        self.assertEqual(self.ledger.read_text(encoding="utf-8"), "PLACEHOLDER")


if __name__ == "__main__":
    unittest.main()
