from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _is_project_file(path: Path) -> bool:
    """Exclude Git internals and the local dependency environment from repository scans."""

    return ".git" not in path.parts and ".venv" not in path.parts


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
            if not _is_project_file(path):
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
            if not _is_project_file(document):
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

    def test_calibration_templates_are_strict_synthetic_and_not_approved(self) -> None:
        profile_schema_path = ROOT / "configs/schemas/calibration-profile.schema.json"
        assessment_schema_path = ROOT / "configs/schemas/calibration-assessment.schema.json"
        profile_path = ROOT / "configs/templates/calibration-profile.template.json"
        assessment_path = ROOT / "configs/templates/calibration-assessment.template.json"
        for path in (
            profile_schema_path,
            assessment_schema_path,
            profile_path,
            assessment_path,
        ):
            self.assertTrue(path.is_file(), path)

        profile_schema = json.loads(profile_schema_path.read_text(encoding="utf-8"))
        assessment_schema = json.loads(assessment_schema_path.read_text(encoding="utf-8"))
        profile_bytes = profile_path.read_bytes()
        profile = json.loads(profile_bytes)
        assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
        for schema in (profile_schema, assessment_schema):
            self.assertIs(schema["additionalProperties"], False)
            self.assertNotIn('"default"', json.dumps(schema))

        self.assertEqual(profile["record_type"], "sensor_calibration_profile")
        self.assertEqual(profile["profile_role_id"], "synthetic-fixture-only")
        self.assertTrue(
            all(item["stream_id"].startswith("synthetic-") for item in profile["cameras"])
        )
        self.assertTrue(
            all(item["stream_id"].startswith("synthetic-") for item in profile["imu_streams"])
        )
        self.assertNotIn("approved_for_replay", profile)
        configuration_fields = (
            "replay_clock_id",
            "camera_layout_id",
            "operating_mode_id",
            "cameras",
            "imu_streams",
            "spatial_calibrations",
            "temporal_calibrations",
            "gravity",
            "validity_conditions",
        )
        expected_fingerprint = hashlib.sha256(
            (
                json.dumps(
                    {field: profile[field] for field in configuration_fields},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(profile["configuration_fingerprint_sha256"], expected_fingerprint)

        self.assertEqual(assessment["record_type"], "calibration_profile_assessment")
        self.assertEqual(assessment["decision"], "rejected")
        self.assertIs(assessment["approved_for_replay"], False)
        self.assertIs(assessment["accepts_adr"], False)
        self.assertEqual(
            assessment["profile_link"]["sha256"],
            hashlib.sha256(profile_bytes).hexdigest(),
        )
        self.assertEqual(
            assessment["profile_link"]["configuration_fingerprint_sha256"],
            expected_fingerprint,
        )

    def test_m2_governance_templates_are_strict_non_authoritative_drafts(self) -> None:
        pairs = {
            "project-release-scope": (
                "project_release_scope",
                "decision_input_only",
                ["draft", "ready_for_owner_review"],
            ),
            "rights-matrix": (
                "rights_matrix",
                "evidence_input_only",
                ["draft", "ready_for_owner_review"],
            ),
            "artifact-storage-plan": (
                "artifact_storage_plan",
                "decision_input_only",
                ["draft", "ready_for_owner_review"],
            ),
            "worker-authorization": (
                "worker_authorization",
                "bounded_action_authorization",
                ["draft", "ready_for_owner_review", "owner_approved"],
            ),
        }
        for stem, (record_type, authority, allowed_statuses) in pairs.items():
            with self.subTest(record=stem):
                schema = json.loads(
                    (ROOT / f"governance/schemas/{stem}.schema.json").read_text(encoding="utf-8")
                )
                template = json.loads(
                    (ROOT / f"governance/records/templates/{stem}.template.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertIs(schema.get("additionalProperties"), False)
                self.assertEqual(
                    schema["properties"]["record_status"]["enum"],
                    allowed_statuses,
                )
                self.assertEqual(template["record_status"], "draft")
                self.assertEqual(schema["properties"]["record_type"]["const"], record_type)
                self.assertEqual(template["record_type"], record_type)
                self.assertEqual(template["authority"], authority)
                self.assertIs(template["accepts_adr"], False)
                self.assertNotIn("default", json.dumps(schema))

        project = json.loads(
            (ROOT / "governance/records/templates/project-release-scope.template.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIsNone(project["purpose_statement"])
        self.assertEqual(project["release_lanes"], [])
        self.assertEqual(project["project_source_license"]["status"], "unresolved")
        self.assertTrue(
            all(value == "unresolved" for value in project["artifact_release_intent"].values())
        )

        rights = json.loads(
            (ROOT / "governance/records/templates/rights-matrix.template.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(rights["assets"], [])
        self.assertIsNone(rights["inventory_complete_for_scope"])

        storage = json.loads(
            (ROOT / "governance/records/templates/artifact-storage-plan.template.json").read_text(
                encoding="utf-8"
            )
        )
        for field in ("primary_vault", "independent_backup", "capacity_envelope", "cost_envelope"):
            self.assertIsNone(storage[field])

        worker = json.loads(
            (ROOT / "governance/records/templates/worker-authorization.template.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIsNone(worker["authorization_kind"])
        self.assertIs(worker["authorizes_work"], False)
        self.assertIs(worker["general_destructive_action_authorized"], False)
        self.assertEqual(worker["requested_action_ids"], [])
        self.assertEqual(worker["action_scopes"], [])
        self.assertIsNone(worker["disposable_restore_test_source_copy"])
        self.assertEqual(worker["max_executions"], 1)
        self.assertFalse(any(worker["permissions"].values()))
        for approval_field in (
            "approved_by",
            "approved_at",
            "approval_statement",
            "approval_evidence_ref",
        ):
            self.assertIsNone(worker[approval_field])

        worker_schema = json.loads(
            (ROOT / "governance/schemas/worker-authorization.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIs(
            worker_schema["properties"]["general_destructive_action_authorized"]["const"],
            False,
        )
        self.assertEqual(worker_schema["properties"]["max_executions"]["const"], 1)
        self.assertIn("action_scopes", worker_schema["required"])
        action_scope = worker_schema["$defs"]["action_scope"]
        self.assertEqual(set(action_scope["required"]), {"action_id", "location_accesses"})
        self.assertEqual(
            action_scope["properties"]["action_id"]["$ref"],
            "#/$defs/action_id",
        )
        location_access = worker_schema["$defs"]["location_access"]
        self.assertEqual(
            set(location_access["properties"]["access"]["enum"]),
            {"read", "write", "delete"},
        )
        owner_approval_rules = [
            rule
            for rule in worker_schema["allOf"]
            if rule.get("if", {}).get("properties", {}).get("record_status", {}).get("const")
            == "owner_approved"
        ]
        self.assertEqual(len(owner_approval_rules), 1)
        self.assertIs(
            owner_approval_rules[0]["then"]["properties"]["authorizes_work"]["const"],
            True,
        )

        action_ids = set(worker_schema["$defs"]["action_id"]["enum"])
        m2_action_ids = set(worker_schema["$defs"]["m2_action_id"]["enum"])
        hard_prohibited = set(worker["hard_prohibited_action_ids"])
        self.assertTrue(hard_prohibited.isdisjoint(action_ids))
        self.assertTrue(
            {"dataset_download", "training", "important_experiment"}.isdisjoint(m2_action_ids)
        )
        self.assertEqual(
            {
                "create_disposable_restore_test_source_copy",
                "write_primary_restore_test_copy",
                "write_independent_backup_restore_test_copy",
                "two_copy_content_audit",
                "disposable_source_copy_delete",
                "representative_restore",
                "representative_load_open",
            }
            - m2_action_ids,
            set(),
        )

        permission_properties = worker_schema["$defs"]["permissions"]["properties"]
        for prohibited_id in hard_prohibited:
            self.assertIs(permission_properties[prohibited_id]["const"], False)

        deletion_rules = [
            rule
            for rule in worker_schema["allOf"]
            if rule.get("if", {})
            .get("properties", {})
            .get("requested_action_ids", {})
            .get("contains", {})
            .get("const")
            == "disposable_source_copy_delete"
        ]
        self.assertEqual(len(deletion_rules), 1)
        deletion_then = deletion_rules[0]["then"]["properties"]
        prerequisites = {
            condition["contains"]["const"]
            for condition in deletion_then["requested_action_ids"]["allOf"]
        }
        self.assertEqual(
            prerequisites,
            {
                "create_disposable_restore_test_source_copy",
                "write_primary_restore_test_copy",
                "write_independent_backup_restore_test_copy",
                "two_copy_content_audit",
                "representative_restore",
                "representative_load_open",
            },
        )
        self.assertIs(
            deletion_then["permissions"]["properties"]["disposable_source_copy_delete"]["const"],
            True,
        )
        disposable_copy_schema = worker_schema["$defs"]["disposable_restore_test_source_copy"]
        self.assertIs(
            disposable_copy_schema["properties"]["purpose_created_for_restore_test"]["const"],
            True,
        )
        self.assertEqual(
            disposable_copy_schema["properties"]["retention_class"]["const"],
            "disposable",
        )

    def test_governance_references_are_credential_free_and_record_ids_are_unique(self) -> None:
        schema_names = (
            "project-release-scope",
            "rights-matrix",
            "artifact-storage-plan",
            "worker-authorization",
        )
        for name in schema_names:
            schema = json.loads(
                (ROOT / f"governance/schemas/{name}.schema.json").read_text(encoding="utf-8")
            )
            pattern = schema["$defs"]["credential_free_reference"]["pattern"]
            with self.subTest(schema=name):
                self.assertIsNotNone(re.fullmatch(pattern, "https://example.invalid/evidence"))
                self.assertIsNone(re.fullmatch(pattern, "https://user@example.invalid/evidence"))
                self.assertIsNone(re.fullmatch(pattern, "//user:secret@example.invalid/evidence"))
                self.assertIsNone(re.fullmatch(pattern, "user:secret@example.invalid:path"))
                self.assertIsNone(re.fullmatch(pattern, "user%3Asecret%40example.invalid"))
                self.assertIsNone(re.fullmatch(pattern, "user%253Asecret%2540example.invalid"))
                self.assertIsNone(
                    re.fullmatch(pattern, "https://example.invalid/path%253Ftoken=secret")
                )
                self.assertIsNone(re.fullmatch(pattern, "https://example.invalid/evidence?token=x"))
                self.assertIsNone(re.fullmatch(pattern, "https://example.invalid/evidence#secret"))

            non_template = schema["$defs"]["non_template_reference"]
            exclusion_patterns = [
                rule["not"]["pattern"] for rule in non_template["allOf"] if "not" in rule
            ]
            self.assertTrue(exclusion_patterns)
            for forbidden in (
                "governance/records/templates/approval.json",
                "governance/records/worker_authorization/request.draft.json",
                "governance/records/worker_authorization/request.template.json",
            ):
                self.assertTrue(
                    any(re.search(rule, forbidden) for rule in exclusion_patterns),
                    f"non-template reference accepted {forbidden!r} in {name}",
                )

        records_root = ROOT / "governance/records"
        for path in sorted(records_root.rglob("*.json")):
            if "templates" in path.parts:
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
            for array_name, id_name in (("release_lanes", "lane_id"), ("assets", "asset_id")):
                if array_name not in record:
                    continue
                identifiers = [item[id_name] for item in record[array_name]]
                self.assertEqual(
                    len(identifiers),
                    len(set(identifiers)),
                    f"duplicate {id_name} in {path.relative_to(ROOT)}",
                )

    def test_governance_real_record_discovery_contract_is_unambiguous(self) -> None:
        record_types = {
            "project_release_scope": "project-release-scope",
            "rights_matrix": "rights-matrix",
            "artifact_storage_plan": "artifact-storage-plan",
            "worker_authorization": "worker-authorization",
        }
        readme = (ROOT / "governance/records/README.md").read_text(encoding="utf-8")
        self.assertIn("governance/records/<record_type>/<record_identifier>.json", readme)

        for record_type, schema_stem in record_types.items():
            schema = json.loads(
                (ROOT / f"governance/schemas/{schema_stem}.schema.json").read_text(encoding="utf-8")
            )
            template = json.loads(
                (ROOT / f"governance/records/templates/{schema_stem}.template.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(schema["properties"]["record_type"]["const"], record_type)
            self.assertEqual(template["record_type"], record_type)

            record_directory = ROOT / "governance/records" / record_type
            for path in sorted(record_directory.glob("*.json")):
                record = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(record["record_type"], record_type)
                self.assertEqual(record["record_id"], path.stem)
                self.assertFalse(path.name.endswith((".template.json", ".draft.json")))

        evidence_schema = json.loads(
            (ROOT / "experiments/schemas/artifact-storage-evidence.schema.json").read_text(
                encoding="utf-8"
            )
        )
        evidence_template = json.loads(
            (ROOT / "governance/records/templates/artifact-storage-evidence.draft.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            evidence_schema["properties"]["record_type"]["const"],
            "artifact_storage_evidence",
        )
        self.assertEqual(evidence_template["record_type"], "artifact_storage_evidence")
        evidence_directory = ROOT / "governance/records/artifact_storage_evidence"
        for path in sorted(evidence_directory.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(record["record_type"], "artifact_storage_evidence")
            self.assertEqual(record["evidence_id"], path.stem)
            self.assertFalse(path.name.endswith((".template.json", ".draft.json")))

    def test_storage_plan_declares_cross_field_semantic_contract(self) -> None:
        schema = json.loads(
            (ROOT / "governance/schemas/artifact-storage-plan.schema.json").read_text(
                encoding="utf-8"
            )
        )
        semantic_contract = schema["$comment"]
        for clause in (
            "distinct primary/backup candidate_id and location_ref",
            "total_required_bytes = worst_case_retained_bytes + reserve_bytes",
            "available_bytes >= total_required_bytes",
            "expected_teardown_transfer_seconds >= total_required_bytes",
            "expected_teardown_transfer_seconds <= cost_envelope.review_at",
        ):
            self.assertIn(clause, semantic_contract)

        for field_schema in schema["$defs"]["evidence_refs"]["properties"].values():
            self.assertEqual(field_schema["anyOf"][0], {"type": "null"})
            self.assertEqual(
                field_schema["anyOf"][1],
                {"$ref": "#/$defs/credential_free_reference"},
            )

    def test_unresolved_release_adr_has_no_license_or_template_exit_evidence(self) -> None:
        adr_0001 = (ROOT / "docs/adr/0001-project-and-release-scope.md").read_text(encoding="utf-8")
        if "- Status: Unresolved" in adr_0001:
            self.assertEqual(sorted(path.name for path in ROOT.glob("LICENSE*")), [])

        authoritative_gate_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ROOT / "docs/plan.md",
                ROOT / "docs/adr/0001-project-and-release-scope.md",
                ROOT / "docs/adr/0005-artifact-storage.md",
            )
        )
        self.assertNotIn(".template.json", authoritative_gate_text)

    def test_m2_cannot_be_complete_while_required_adrs_are_unresolved(self) -> None:
        adr_statuses = []
        for name in (
            "0001-project-and-release-scope.md",
            "0005-artifact-storage.md",
        ):
            text = (ROOT / "docs/adr" / name).read_text(encoding="utf-8")
            match = re.search(r"^- Status: ([A-Za-z]+)$", text, re.MULTILINE)
            self.assertIsNotNone(match)
            assert match is not None
            adr_statuses.append(match.group(1))

        if any(status != "Accepted" for status in adr_statuses):
            plan = (ROOT / "docs/plan.md").read_text(encoding="utf-8")
            m2 = re.search(
                r"^## M2 —[^\n]+\n\nStatus: ([^\n]+)",
                plan,
                flags=re.MULTILINE,
            )
            self.assertIsNotNone(m2)
            assert m2 is not None
            self.assertEqual(m2.group(1), "Blocked.")

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
