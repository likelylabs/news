"""Regression coverage for the article-to-index publishing boundary (stdlib only)."""
import contextlib
import copy
from datetime import datetime, timedelta
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools" / "build_index.py"
spec = importlib.util.spec_from_file_location("build_index", SCRIPT)
build_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_index)
NOW = datetime(2026, 10, 18, 12, tzinfo=build_index.HKT)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz)


def article(slug="example", published_at=None):
    published_at = published_at or NOW.isoformat(timespec="seconds")
    return {
        "id": f"{published_at[:10]}-{slug}",
        "published_at": published_at,
        "category": "business",
        "tags": ["hong-kong", "investment"],
        "ai_generated": True,
        "en": {
            "headline": "Hong Kong welcomes new enterprises",
            "dek": "New enterprises announced plans to expand their Hong Kong operations.",
            "body": ["The first paragraph is retained in full.", "The second paragraph is retained in full."],
        },
        "zh": {
            "headline": "香港迎來新一批重點企業落戶",
            "dek": "新一批重點企業宣布計劃在香港擴展業務。",
            "body": ["首段報道內容完整保留。", "第二段報道內容完整保留。"],
        },
    }


class BuildIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.articles = self.repo / "articles"
        self.index = self.repo / "index.json"
        self.index.write_text('{"previous": "index"}\n', encoding="utf-8")
        for name, value in (("REPO", self.repo), ("ARTICLES_DIR", self.articles),
                            ("INDEX_PATH", self.index), ("datetime", FixedDateTime)):
            patcher = patch.object(build_index, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_article(self, data, name=None):
        aid = name or data["id"]
        path = self.articles / aid[:10] / f"{aid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def snapshot(self):
        return {str(path.relative_to(self.repo)): path.read_bytes()
                for path in self.repo.rglob("*") if path.is_file()}

    def run_build(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = build_index.main(list(args))
        return status, stdout.getvalue(), stderr.getvalue()

    def test_incident_ampersand_tag_is_repaired_without_changing_article_content(self):
        original = article("oases-next-batch-strategic-enterprises")
        original["tags"] = ["oases", "investment", "pharma", "i&t"]
        path = self.write_article(original)

        status, stdout, stderr = self.run_build()

        self.assertEqual(status, 0, stderr)
        expected = copy.deepcopy(original)
        expected["tags"][-1] = "i-t"
        self.assertEqual(json.loads(path.read_text()), expected)
        index = json.loads(self.index.read_text())
        self.assertEqual(index["count"], 1)
        self.assertEqual(index["articles"][0]["tags"], expected["tags"])
        self.assertIn("auto-normalized", stdout)
        before = self.snapshot()
        self.assertEqual(self.run_build()[0], 0)
        self.assertEqual(self.snapshot(), before, "a second build must be idempotent")

    def test_ascii_normalization_deduplicates_and_caps_in_original_order(self):
        original = article()
        original["tags"] = ["  Hong_Kong! ", "I&T", "i-t", "start...ups",
                            "health/care", "BUSINESS", "sixth", "seventh"]
        path = self.write_article(original)
        self.assertEqual(self.run_build()[0], 0)
        self.assertEqual(json.loads(path.read_text())["tags"],
                         ["hong-kong", "i-t", "start-ups", "health-care", "business", "sixth"])

    def test_cap_preserves_lifestyle_tag_when_it_would_otherwise_be_dropped(self):
        original = article()
        original["tags"] = ["one", "two", "three", "four", "five", "six", "seven", "Lifestyle"]
        path = self.write_article(original)
        self.assertEqual(self.run_build()[0], 0)
        self.assertEqual(json.loads(path.read_text())["tags"],
                         ["one", "two", "three", "four", "five", "lifestyle"])

    def test_unrepresentable_tags_remain_errors_even_beyond_cap(self):
        invalid = [None, 7, {}, [], "香港", "café", "", " &! ", "bad\x00tag"]
        for value in invalid:
            with self.subTest(tag=value):
                original = article()
                original["tags"] = ["one", "two", "three", "four", "five", "six", value]
                self.write_article(original)
                before = self.snapshot()
                status, _, stderr = self.run_build()
                self.assertEqual(status, 1)
                self.assertIn("'tags'", stderr)
                self.assertEqual(self.snapshot(), before)

    def test_existing_headline_and_dek_trimming_is_preserved(self):
        original = article()
        original["en"]["headline"] = "Enterprise expansion " * 10
        original["zh"]["dek"] = "企業公布擴展業務計劃" * 30
        path = self.write_article(original)
        self.assertEqual(self.run_build()[0], 0)
        result = json.loads(path.read_text())
        self.assertLessEqual(len(result["en"]["headline"]), 90)
        self.assertTrue(result["en"]["headline"].endswith("…"))
        self.assertLessEqual(len(result["zh"]["dek"]), 220)
        self.assertEqual(result["en"]["body"], original["en"]["body"])
        self.assertEqual(result["zh"]["body"], original["zh"]["body"])

    def test_validation_failure_leaves_every_pending_article_and_index_unchanged(self):
        first = article("a-repairable")
        first["tags"] = ["i&t"]
        first["en"]["headline"] = "Long headline " * 20
        self.write_article(first)
        self.write_article(article("m-valid"))
        last = article("z-invalid")
        last["category"] = "unknown"
        self.write_article(last)
        before = self.snapshot()

        status, stdout, stderr = self.run_build()

        self.assertEqual(status, 1)
        self.assertIn("'category'", stderr)
        self.assertNotIn("auto-normalized", stdout)
        self.assertEqual(self.snapshot(), before)

    def test_invalid_json_keeps_pending_normalizations_unwritten(self):
        first = article("a-repairable")
        first["tags"] = ["I&T"]
        self.write_article(first)
        path = self.write_article(article("z-invalid-json"))
        path.write_text("{invalid", encoding="utf-8")
        before = self.snapshot()
        status, _, stderr = self.run_build()
        self.assertEqual(status, 1)
        self.assertIn("invalid JSON", stderr)
        self.assertEqual(self.snapshot(), before)

    def test_check_rejects_raw_inputs_that_build_would_normalize(self):
        for changes in ({"tags": ["i&t"]}, {"tags": ["same", "same"]},
                        {"tags": ["a", "b", "c", "d", "e", "f", "g"]},
                        {"en": {**article()["en"], "headline": "A" * 91}}):
            with self.subTest(changes=changes):
                self.write_article({**article(), **changes})
                before = self.snapshot()
                self.assertEqual(self.run_build("--check")[0], 1)
                self.assertEqual(self.snapshot(), before)

    def test_check_valid_corpus_is_read_only_even_without_existing_index(self):
        self.write_article(article())
        before = self.snapshot()
        self.assertEqual(self.run_build("--check")[0], 0)
        self.assertEqual(self.snapshot(), before)
        self.index.unlink()
        before = self.snapshot()
        self.assertEqual(self.run_build("--check")[0], 0)
        self.assertEqual(self.snapshot(), before)

    def test_check_cli_exits_nonzero_without_modifying_any_file(self):
        original = article()
        original["tags"] = ["I&T"]
        self.write_article(original)
        script = self.repo / "tools" / "build_index.py"
        script.parent.mkdir()
        shutil.copyfile(SCRIPT, script)
        before = self.snapshot()
        result = subprocess.run([sys.executable, str(script), "--check"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("'tags'", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_malformed_json_types_report_validation_errors(self):
        cases = [None, [], "text", 1]
        for field, values in (
            ("category", [[], {}, None, 1]),
            ("tags", [None, "tag", {}, 1, [{}], [[]]]),
            ("en", [None, [], "text"]),
            ("published_at", [None, [], {}, 1]),
            ("updated_at", [None, [], {}]),
            ("story_key", [None, [], {}]),
        ):
            cases.extend({**article(), field: value} for value in values)
        for original in cases:
            with self.subTest(article=original):
                self.write_article(original, name="2026-10-18-example")
                before = self.snapshot()
                for args in ((), ("--check",)):
                    status, _, stderr = self.run_build(*args)
                    self.assertEqual(status, 1)
                    self.assertIn("VALIDATION FAILED", stderr)
                    self.assertNotIn("Traceback", stderr)
                    self.assertEqual(self.snapshot(), before)

    def test_null_required_localized_fields_are_invalid(self):
        for lang in ("en", "zh"):
            for field in ("headline", "dek", "body"):
                with self.subTest(language=lang, field=field):
                    original = article()
                    original[lang][field] = None
                    self.write_article(original)
                    status, _, stderr = self.run_build()
                    self.assertEqual(status, 1)
                    self.assertIn(f"'{lang}.{field}'", stderr)

    def test_invalid_calendar_timestamps_report_errors_without_tracebacks(self):
        invalid = ["2026-02-30T12:00:00+08:00", "2026-13-18T12:00:00+08:00",
                   "2026-10-18T24:00:00+08:00", "2026-10-18T12:00:60+08:00",
                   "0000-10-18T12:00:00+08:00", "2026-10-18T12:00:00+09:00",
                   "2026-10-18T12:00:00+08:00\n"]
        for field in ("published_at", "updated_at"):
            for value in invalid:
                with self.subTest(field=field, value=value):
                    original = article()
                    original[field] = value
                    self.write_article(original)
                    before = self.snapshot()
                    for args in ((), ("--check",)):
                        status, _, stderr = self.run_build(*args)
                        self.assertEqual(status, 1)
                        self.assertIn(f"'{field}'", stderr)
                        self.assertEqual(self.snapshot(), before)

    def test_valid_corpus_retains_archive_and_builds_sorted_live_window(self):
        old = article("old", (NOW - timedelta(hours=73)).isoformat(timespec="seconds"))
        edge = article("edge", (NOW - timedelta(hours=72)).isoformat(timespec="seconds"))
        recent = article("recent")
        del recent["tags"]
        recent["updated_at"] = recent["published_at"]
        paths = [self.write_article(data) for data in (old, edge, recent)]
        original_bytes = {path: path.read_bytes() for path in paths}
        status, _, stderr = self.run_build()
        self.assertEqual(status, 0, stderr)
        index = json.loads(self.index.read_text())
        self.assertEqual(index["live_window_hours"], 72)
        self.assertEqual(index["count"], 2)
        self.assertEqual([entry["id"] for entry in index["articles"]], [recent["id"], edge["id"]])
        self.assertEqual(index["articles"][0]["tags"], [])
        self.assertFalse(index["articles"][0]["breaking"])
        self.assertEqual({path: path.read_bytes() for path in paths}, original_bytes)
        self.assertEqual(self.run_build("--check")[0], 0)


class SchemaContractTests(unittest.TestCase):
    def test_schema_timestamp_regex_accepts_actual_hong_kong_timestamps(self):
        schema = json.loads((REPO / "schema" / "article.schema.json").read_text())
        for field in ("published_at", "updated_at"):
            pattern = schema["properties"][field]["pattern"]
            self.assertIsNotNone(re.fullmatch(pattern, "2026-10-18T07:00:00+08:00"))
            self.assertIsNone(re.fullmatch(pattern, "2026-10-18T07:00:00+09:00"))
        tags = schema["properties"]["tags"]
        self.assertEqual(tags["maxItems"], build_index.MAX_TAGS)
        self.assertTrue(tags["uniqueItems"])
        self.assertIsNotNone(re.fullmatch(tags["items"]["pattern"], "i-t"))
        self.assertIsNone(re.fullmatch(tags["items"]["pattern"], "i&t"))
        self.assertEqual(set(schema["properties"]["category"]["enum"]), build_index.CATEGORIES)


if __name__ == "__main__":
    unittest.main()
