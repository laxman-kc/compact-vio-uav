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

    def test_requirement_ids_are_unique(self) -> None:
        document = ROOT / "docs/requirements/project-requirements.md"
        requirement_ids = re.findall(
            r"^\| (R-[A-Z]+-\d{3}) \|",
            document.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
        self.assertTrue(requirement_ids)
        self.assertEqual(len(requirement_ids), len(set(requirement_ids)))

    def test_requirements_index_does_not_define_requirements(self) -> None:
        document = (ROOT / "docs/requirements.md").read_text(encoding="utf-8")
        definitions = re.findall(r"^\| R-[A-Z]+-\d{3} \|", document, re.MULTILINE)
        self.assertEqual(definitions, [])

    def test_adr_index_matches_files_and_statuses(self) -> None:
        index_text = (ROOT / "docs/adr/README.md").read_text(encoding="utf-8")
        index_rows = re.findall(
            r"^\| \[(\d{4})\]\(([^)]+)\) \|.*\| ([A-Za-z]+) \|",
            index_text,
            flags=re.MULTILINE,
        )
        indexed = {adr_id: (target, status) for adr_id, target, status in index_rows}
        self.assertEqual(len(indexed), len(index_rows))

        files = sorted((ROOT / "docs/adr").glob("[0-9][0-9][0-9][0-9]-*.md"))
        self.assertEqual(len(indexed), len(files))
        for file_path in files:
            text = file_path.read_text(encoding="utf-8")
            heading = re.search(r"^# ADR-(\d{4}):", text, re.MULTILINE)
            status = re.search(r"^- Status: ([A-Za-z]+)$", text, re.MULTILINE)
            self.assertIsNotNone(heading, file_path)
            self.assertIsNotNone(status, file_path)
            assert heading is not None
            assert status is not None
            adr_id = heading.group(1)
            self.assertEqual(file_path.name[:4], adr_id)
            self.assertIn(adr_id, indexed)
            self.assertEqual(indexed[adr_id], (file_path.name, status.group(1)))
            if status.group(1) == "Accepted":
                self.assertNotIn("- Decision owner: TBD", text)
                self.assertRegex(text, r"- Decision date: \d{4}-\d{2}-\d{2}")
                for section in (
                    "## Decision",
                    "## Evidence",
                    "## Rejected alternatives",
                    "## Consequences",
                    "## Follow-up",
                ):
                    self.assertIn(section, text)

    def test_plan_references_known_milestones_adrs_and_requirements(self) -> None:
        plan_text = (ROOT / "docs/plan.md").read_text(encoding="utf-8")
        milestone_ids = re.findall(r"^## (M\d+) —", plan_text, re.MULTILINE)
        self.assertTrue(milestone_ids)
        self.assertEqual(len(milestone_ids), len(set(milestone_ids)))

        milestone_references = set(re.findall(r"\bM\d+\b", plan_text))
        self.assertEqual(milestone_references - set(milestone_ids), set())

        adr_ids = {
            match.group(1)
            for adr_file in (ROOT / "docs/adr").glob("[0-9][0-9][0-9][0-9]-*.md")
            if (match := re.search(r"^# (ADR-\d{4}):", adr_file.read_text(encoding="utf-8")))
        }
        self.assertEqual(set(re.findall(r"\bADR-\d{4}\b", plan_text)) - adr_ids, set())

        requirements_text = (ROOT / "docs/requirements/project-requirements.md").read_text(
            encoding="utf-8"
        )
        requirement_ids = set(
            re.findall(r"^\| (R-[A-Z]+-\d{3}) \|", requirements_text, re.MULTILINE)
        )
        explicit_references = set(re.findall(r"\bR-[A-Z]+-\d{3}\b", plan_text))
        self.assertEqual(explicit_references - requirement_ids, set())

        requirement_groups = {requirement_id.split("-")[1] for requirement_id in requirement_ids}
        wildcard_groups = set(re.findall(r"\bR-([A-Z]+)-\*", plan_text))
        self.assertEqual(wildcard_groups - requirement_groups, set())

    def test_plan_overview_matches_sections_and_dependencies_are_acyclic(self) -> None:
        plan_text = (ROOT / "docs/plan.md").read_text(encoding="utf-8")
        overview_rows = re.findall(
            r"^\| (M\d+) \| ([^|]+?) \| ([^|]+?) \|",
            plan_text,
            flags=re.MULTILINE,
        )
        overview = {
            milestone_id: (title.strip(), status.strip())
            for milestone_id, title, status in overview_rows
        }

        section_pattern = re.compile(
            r"^## (M\d+) — ([^\n]+)\n\nStatus: ([^\n]+)\n(?P<body>.*?)(?=^## M\d+ —|\Z)",
            flags=re.MULTILINE | re.DOTALL,
        )
        sections = list(section_pattern.finditer(plan_text))
        self.assertEqual(len(overview), len(sections))
        for section in sections:
            milestone_id, title, status = section.group(1, 2, 3)
            normalized_status = status.removesuffix(".")
            self.assertEqual(overview[milestone_id], (title, normalized_status))

            dependency_match = re.search(
                r"^Dependencies: (?P<value>.*?)(?=\n\n)",
                section.group("body"),
                flags=re.MULTILINE | re.DOTALL,
            )
            self.assertIsNotNone(dependency_match, milestone_id)
            assert dependency_match is not None
            current_number = int(milestone_id[1:])
            for dependency in re.findall(r"\bM(\d+)\b", dependency_match.group("value")):
                self.assertLess(int(dependency), current_number)

    def test_progress_references_known_milestones(self) -> None:
        plan_text = (ROOT / "docs/plan.md").read_text(encoding="utf-8")
        progress_text = (ROOT / "docs/progress.md").read_text(encoding="utf-8")
        milestone_ids = set(re.findall(r"^## (M\d+) —", plan_text, re.MULTILINE))
        progress_references = set(re.findall(r"\bM\d+\b", progress_text))
        self.assertEqual(progress_references - milestone_ids, set())
        entry_headings = re.findall(
            r"^## (\d{4}-\d{2}-\d{2}) — (M\d+)\b",
            progress_text,
            flags=re.MULTILINE,
        )
        self.assertTrue(entry_headings)
        self.assertEqual(
            {milestone for _, milestone in entry_headings} - milestone_ids,
            set(),
        )


if __name__ == "__main__":
    unittest.main()
