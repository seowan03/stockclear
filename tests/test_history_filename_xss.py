import re
import unittest
from pathlib import Path


class HistoryFilenameXssTests(unittest.TestCase):
    def test_history_filename_is_rendered_as_text(self):
        history_page = Path(__file__).resolve().parents[1] / "static" / "history.html"
        source = history_page.read_text(encoding="utf-8")

        self.assertIn("cell.append(...children)", source)
        self.assertIn("String(row.file_name ?? '')", source)
        self.assertNotRegex(source, re.compile(r"\$\{\s*row\.file_name\b"))


if __name__ == "__main__":
    unittest.main()