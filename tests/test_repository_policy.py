from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from compact_vio.repository_policy import check_paths


class RepositoryPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write(self, relative: str, content: bytes) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def test_clean_files_pass(self) -> None:
        self.write("README.md", b"# clean\n")
        self.write("src/module.py", b"VALUE = 1\n")

        self.assertEqual(check_paths(self.root, ["README.md", "src/module.py"]), ())

    def test_reports_all_policy_violations_deterministically(self) -> None:
        self.write("large.txt", b"x" * 11)
        self.write("model.onnx", b"small")
        self.write("invalid.md", b"bad\x00\xff")

        violations = check_paths(
            self.root,
            [
                "model.onnx",
                "large.txt",
                "invalid.md",
                "missing.txt",
                "../escape",
                ".",
            ],
            max_bytes=10,
        )

        self.assertEqual(list(violations), sorted(violations))
        self.assertEqual(
            {violation.code for violation in violations},
            {
                "unsafe_path",
                "missing",
                "file_too_large",
                "forbidden_artifact",
                "text_nul",
                "invalid_utf8",
            },
        )

    def test_secret_values_are_never_returned(self) -> None:
        github_token = b"gh" + b"p_" + b"A" * 36
        aws_key = b"AK" + b"IA" + b"B" * 16
        private_key = b"-----BEGIN " + b"PRIVATE KEY-----"
        content = b"\n".join((github_token, aws_key, private_key))
        self.write("leak.txt", content)

        violations = check_paths(self.root, ["leak.txt"])
        serialized = json.dumps([violation.to_dict() for violation in violations])

        self.assertEqual(
            {violation.code for violation in violations},
            {"secret_github_token", "secret_aws_access_key", "secret_private_key"},
        )
        self.assertNotIn(github_token.decode(), serialized)
        self.assertNotIn(aws_key.decode(), serialized)
        self.assertNotIn(private_key.decode(), serialized)

    def test_symlink_is_rejected(self) -> None:
        self.write("target.txt", b"target")
        link = self.root / "link.txt"
        try:
            link.symlink_to("target.txt")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")

        violations = check_paths(self.root, ["link.txt"])

        self.assertEqual([violation.code for violation in violations], ["symlink"])


if __name__ == "__main__":
    unittest.main()
