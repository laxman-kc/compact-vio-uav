from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


class FoundationFileTests(unittest.TestCase):
    def test_all_json_is_utf8_without_duplicate_object_keys(self) -> None:
        json_paths = sorted(ROOT.rglob("*.json"))
        self.assertTrue(json_paths)
        for path in json_paths:
            if ".git" in path.parts:
                continue
            with self.subTest(path=path.relative_to(ROOT)):
                json.loads(
                    path.read_text(encoding="utf-8"),
                    object_pairs_hook=_reject_duplicate_keys,
                )

    def test_local_markdown_links_resolve(self) -> None:
        link_pattern = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
        missing: list[tuple[str, str]] = []
        for document in sorted(ROOT.rglob("*.md")):
            if ".git" in document.parts:
                continue
            for target in link_pattern.findall(document.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                local_target = target.split("#", 1)[0]
                if local_target and not (document.parent / local_target).resolve().exists():
                    missing.append((str(document.relative_to(ROOT)), target))
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
