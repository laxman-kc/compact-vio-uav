from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import stat
import tarfile
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from compact_vio.data.archive import (
    ArchiveError,
    AuthorizedArchiveAcquisition,
    PublishedArchiveIdentity,
    TarLimits,
    TarStructuralMemberRecord,
    _ExactRedirectHandler,
    audit_tar_structure,
    download_archive,
    extract_tar,
    inventory_tar,
    load_authorized_archive_acquisition,
    load_dataset_archive_candidate,
    verify_archive,
)


def _identity(
    content: bytes,
    *,
    sha256: str | None = None,
    allowed_redirect_urls: tuple[str, ...] = (),
    allowed_redirect_origins: tuple[str, ...] = (),
) -> PublishedArchiveIdentity:
    return PublishedArchiveIdentity(
        archive_id="room4-512-16",
        filename="dataset-room4.tar",
        url="https://cdn3.example.invalid/dataset-room4.tar",
        size_bytes=len(content),
        md5=hashlib.md5(content).hexdigest(),
        sha256=sha256,
        allowed_redirect_urls=allowed_redirect_urls,
        allowed_redirect_origins=allowed_redirect_origins,
    )


def _authorization(
    identity: PublishedArchiveIdentity,
    destination: Path,
) -> AuthorizedArchiveAcquisition:
    document = {
        "record_type": "dataset_archive_acquisition_authorization",
        "schema_version": "1.0.0",
        "record_status": "approved",
        "authorization_record_id": "synthetic-test-authorization",
        "scope": "archive_acquisition_only",
        "reviewed_by": "synthetic-test-reviewer",
        "reviewed_at": "2026-08-28T15:00:00Z",
        "authority": {
            "approves_acquisition": True,
            "approves_extraction": False,
        },
        "archive_identity": {
            "archive_id": identity.archive_id,
            "filename": identity.filename,
            "url": identity.url,
            "size_bytes": identity.size_bytes,
            "md5": identity.md5,
            "sha256": identity.sha256,
            "allowed_redirect_urls": list(identity.allowed_redirect_urls),
            "allowed_redirect_origins": list(identity.allowed_redirect_origins),
        },
        "destination_path": str(destination.absolute()),
    }
    path = destination.parent / ".synthetic-acquisition-authorization.json"
    path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    return load_authorized_archive_acquisition(path, identity)


def _write_tar(path: Path, members: list[tuple[tarfile.TarInfo, bytes | None]]) -> None:
    with tarfile.open(path, "w") as archive:
        for member, content in members:
            archive.addfile(member, io.BytesIO(content) if content is not None else None)


def _file(name: str, content: bytes) -> tuple[tarfile.TarInfo, bytes]:
    member = tarfile.TarInfo(name)
    member.size = len(content)
    return member, content


def _directory(name: str) -> tuple[tarfile.TarInfo, None]:
    member = tarfile.TarInfo(name)
    member.type = tarfile.DIRTYPE
    member.size = 0
    return member, None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _accept_staging(
    _staging: Path,
    _receipts: tuple[object, ...],
) -> None:
    return None


def _candidate_path() -> Path:
    return Path(__file__).resolve().parents[1] / "configs/data/tumvi_room4_512_16_candidate_v1.json"


def _candidate_document() -> dict[str, object]:
    document = json.loads(_candidate_path().read_text(encoding="utf-8"))
    assert type(document) is dict
    return document


def _write_candidate(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


class _Response(io.BytesIO):
    def __init__(
        self,
        content: bytes,
        *,
        status: int,
        headers: dict[str, str],
        url: str,
    ) -> None:
        super().__init__(content)
        self.status = status
        self.headers = headers
        self._url = url

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return self._url


class PublishedArchiveIdentityTests(unittest.TestCase):
    def test_unresolved_identity_computes_sha_without_mutation(self) -> None:
        content = b"publisher-identified bytes"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / identity.filename
            archive.write_bytes(content)

            result = verify_archive(archive, identity)

        self.assertIsNone(identity.sha256)
        self.assertEqual(result.md5, hashlib.md5(content).hexdigest())
        self.assertEqual(result.sha256, hashlib.sha256(content).hexdigest())

    def test_pinned_identity_rejects_wrong_sha(self) -> None:
        content = b"archive"
        identity = _identity(content, sha256="0" * 64)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / identity.filename
            archive.write_bytes(content)
            with self.assertRaisesRegex(ArchiveError, "SHA-256 mismatch"):
                verify_archive(archive, identity)

    def test_identity_rejects_unsafe_urls_and_redirect_policy(self) -> None:
        content = b"archive"
        values = (
            "http://example.invalid/archive.tar",
            "https://user@example.invalid/archive.tar",
            "https://example.invalid/archive.tar#fragment",
        )
        for url in values:
            with self.subTest(url=url), self.assertRaises(ArchiveError):
                PublishedArchiveIdentity(
                    "archive",
                    "archive.tar",
                    url,
                    len(content),
                    hashlib.md5(content).hexdigest(),
                )
        with self.assertRaisesRegex(ArchiveError, "scheme and authority"):
            _identity(
                content,
                allowed_redirect_origins=("https://cdn2.example.invalid/path",),
            )

    def test_verify_rejects_symlink_archive(self) -> None:
        content = b"archive"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tar"
            source.write_bytes(content)
            link = root / identity.filename
            link.symlink_to(source)
            with self.assertRaisesRegex(ArchiveError, "non-symlink"):
                verify_archive(link, identity)


class DatasetArchiveCandidateTests(unittest.TestCase):
    def test_loads_exact_non_executable_published_identity(self) -> None:
        candidate = load_dataset_archive_candidate(_candidate_path())

        self.assertEqual(candidate.dataset_id, "tum-vi")
        self.assertEqual(candidate.sequence_id, "room4")
        self.assertEqual(candidate.published_identity.size_bytes, 1_356_206_080)
        self.assertEqual(
            candidate.published_identity.md5,
            "8e2ec2c35ee40a54c9aaa5bc2b3c9d8c",
        )
        self.assertIsNone(candidate.published_identity.sha256)
        self.assertEqual(candidate.md5_sidecar.exact_body[-1], "\n")
        self.assertEqual(len(candidate.md5_sidecar.exact_body.encode()), 59)

    def test_rejects_unknown_and_missing_fields(self) -> None:
        for mode in ("unknown", "missing"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                document = _candidate_document()
                if mode == "unknown":
                    document["unexpected"] = True
                else:
                    del document["record_status"]
                path = Path(directory) / "candidate.json"
                _write_candidate(path, document)
                with self.assertRaisesRegex(ArchiveError, "fields must equal"):
                    load_dataset_archive_candidate(path)

    def test_rejects_any_authority_or_received_byte_promotion(self) -> None:
        mutations = (
            ("authority", "approves_acquisition", True),
            ("candidate_unit", "received_size_bytes", 1_356_206_080),
            ("candidate_unit", "received_md5", "8e2ec2c35ee40a54c9aaa5bc2b3c9d8c"),
            ("candidate_unit", "received_sha256", "0" * 64),
        )
        for section, field, value in mutations:
            with (
                self.subTest(section=section, field=field),
                tempfile.TemporaryDirectory() as directory,
            ):
                document = _candidate_document()
                nested = document[section]
                assert type(nested) is dict
                nested[field] = value
                path = Path(directory) / "candidate.json"
                _write_candidate(path, document)
                with self.assertRaises(ArchiveError):
                    load_dataset_archive_candidate(path)

    def test_rejects_unsafe_or_unbound_candidate_urls(self) -> None:
        mutations = (
            ("official_request_url", "http://example.invalid/archive.tar"),
            (
                "official_request_url",
                "https://cdn3.vision.in.tum.de/archive.tar?mutable=1",
            ),
            (
                "allowed_redirect_urls",
                ["https://unexpected.example.invalid/dataset-room4_512_16.tar"],
            ),
        )
        for field, value in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                document = _candidate_document()
                unit = document["candidate_unit"]
                assert type(unit) is dict
                unit[field] = value
                path = Path(directory) / "candidate.json"
                _write_candidate(path, document)
                with self.assertRaises(ArchiveError):
                    load_dataset_archive_candidate(path)

    def test_rejects_sidecar_without_exact_trailing_lf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            document = _candidate_document()
            unit = document["candidate_unit"]
            assert type(unit) is dict
            sidecar = unit["md5_sidecar"]
            assert type(sidecar) is dict
            sidecar["exact_body"] = str(sidecar["exact_body"]).rstrip("\n")
            path = Path(directory) / "candidate.json"
            _write_candidate(path, document)
            with self.assertRaisesRegex(ArchiveError, "byte length"):
                load_dataset_archive_candidate(path)


class DownloadArchiveTests(unittest.TestCase):
    def test_redirect_handler_validates_every_ordered_hop(self) -> None:
        content = b"archive"
        first = "https://cdn2.example.invalid/dataset-room4.tar"
        second = "https://cdn1.example.invalid/dataset-room4.tar"
        identity = _identity(
            content,
            allowed_redirect_urls=(first, second),
            allowed_redirect_origins=(
                "https://cdn2.example.invalid",
                "https://cdn1.example.invalid",
            ),
        )
        handler = _ExactRedirectHandler(identity)
        request = urllib.request.Request(identity.url)
        first_request = handler.redirect_request(request, None, 302, "Found", {}, first)
        assert first_request is not None
        handler.redirect_request(first_request, None, 302, "Found", {}, second)
        self.assertEqual(handler.redirect_chain, [first, second])
        with self.assertRaisesRegex(ArchiveError, "not exactly allowlisted"):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://rogue.example.invalid/dataset-room4.tar",
            )

    def test_resumes_only_an_exact_range_and_atomically_publishes(self) -> None:
        content = b"complete archive bytes"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / identity.filename
            prefix = content[:9]
            target.with_name(f"{target.name}.part").write_bytes(prefix)
            response = _Response(
                content[len(prefix) :],
                status=206,
                headers={
                    "Content-Length": str(len(content) - len(prefix)),
                    "Content-Range": f"bytes {len(prefix)}-{len(content) - 1}/{len(content)}",
                    "Content-Encoding": "identity",
                },
                url=identity.url,
            )
            with mock.patch(
                "compact_vio.data.archive._open_download_response",
                return_value=(response, ()),
            ) as open_response:
                result = download_archive(_authorization(identity, target), target, chunk_size=3)

            request = open_response.call_args.args[1]
            self.assertEqual(request.get_header("Range"), f"bytes={len(prefix)}-")
            self.assertEqual(request.get_header("Accept-encoding"), "identity")
            self.assertEqual(target.read_bytes(), content)
            self.assertFalse(target.with_name(f"{target.name}.part").exists())
            self.assertEqual(result.sha256, hashlib.sha256(content).hexdigest())
            self.assertEqual(result.resolved_url, identity.url)
            self.assertEqual(
                result.authorization_record_id,
                "synthetic-test-authorization",
            )
            self.assertIsNotNone(result.authorization_record_sha256)

    def test_safely_restarts_when_server_ignores_range(self) -> None:
        content = b"complete archive bytes"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / identity.filename
            partial = target.with_name(f"{target.name}.part")
            partial.write_bytes(b"old")
            response = _Response(
                content,
                status=200,
                headers={"Content-Length": str(len(content))},
                url=identity.url,
            )
            with mock.patch(
                "compact_vio.data.archive._open_download_response",
                return_value=(response, ()),
            ):
                download_archive(_authorization(identity, target), target)

            self.assertEqual(target.read_bytes(), content)
            self.assertFalse(partial.exists())

    def test_bad_range_is_rejected_without_modifying_partial(self) -> None:
        content = b"complete archive bytes"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / identity.filename
            partial = target.with_name(f"{target.name}.part")
            partial.write_bytes(content[:3])
            response = _Response(
                content[3:],
                status=206,
                headers={
                    "Content-Length": str(len(content) - 3),
                    "Content-Range": f"bytes 4-{len(content) - 1}/{len(content)}",
                },
                url=identity.url,
            )
            with (
                mock.patch(
                    "compact_vio.data.archive._open_download_response",
                    return_value=(response, ()),
                ),
                self.assertRaisesRegex(ArchiveError, "Content-Range"),
            ):
                download_archive(_authorization(identity, target), target)

            self.assertEqual(partial.read_bytes(), content[:3])
            self.assertFalse(target.exists())

    def test_multiply_linked_partial_is_rejected_without_mutating_other_link(self) -> None:
        content = b"complete archive bytes"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / identity.filename
            partial = target.with_name(f"{target.name}.part")
            other = root / "unrelated.bin"
            original = content[:7]
            other.write_bytes(original)
            os.link(other, partial)
            with (
                mock.patch("compact_vio.data.archive._open_download_response") as open_response,
                self.assertRaisesRegex(ArchiveError, "singly-linked"),
            ):
                download_archive(_authorization(identity, target), target)
            open_response.assert_not_called()
            self.assertEqual(other.read_bytes(), original)
            self.assertEqual(partial.read_bytes(), original)
            self.assertFalse(target.exists())

    def test_redirect_must_match_exact_url_and_origin_allowlists(self) -> None:
        content = b"archive"
        final_url = "https://cdn2.example.invalid/dataset-room4.tar"
        identity = _identity(
            content,
            allowed_redirect_urls=(final_url,),
            allowed_redirect_origins=("https://cdn2.example.invalid",),
        )
        response = _Response(
            content,
            status=200,
            headers={"Content-Length": str(len(content))},
            url=final_url,
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / identity.filename
            with mock.patch(
                "compact_vio.data.archive._open_download_response",
                return_value=(response, (final_url,)),
            ):
                download_archive(_authorization(identity, target), target)
            self.assertEqual(target.read_bytes(), content)

        unsafe_response = _Response(
            content,
            status=200,
            headers={"Content-Length": str(len(content))},
            url="https://other.example.invalid/dataset-room4.tar",
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / identity.filename
            with (
                mock.patch(
                    "compact_vio.data.archive._open_download_response",
                    return_value=(
                        unsafe_response,
                        ("https://other.example.invalid/dataset-room4.tar",),
                    ),
                ),
                self.assertRaisesRegex(ArchiveError, "redirect allowlist"),
            ):
                download_archive(_authorization(identity, target), target)

    def test_download_enforces_oversize_ceiling(self) -> None:
        content = b"archive"
        identity = _identity(content)
        response = _Response(
            content + b"unexpected",
            status=200,
            headers={"Content-Length": str(len(content))},
            url=identity.url,
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / identity.filename
            with (
                mock.patch(
                    "compact_vio.data.archive._open_download_response",
                    return_value=(response, ()),
                ),
                self.assertRaisesRegex(ArchiveError, "exceeded"),
            ):
                download_archive(_authorization(identity, target), target)
            self.assertFalse(target.exists())

    def test_exclusive_lock_rejects_a_second_writer(self) -> None:
        content = b"archive"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / identity.filename
            lock = target.parent / f".{target.name}.acquire.lock"
            with lock.open("w+b") as lock_handle:
                fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with (
                    mock.patch("compact_vio.data.archive._open_download_response") as open_response,
                    self.assertRaisesRegex(ArchiveError, "already active"),
                ):
                    download_archive(_authorization(identity, target), target)
            open_response.assert_not_called()

    def test_successful_acquisition_releases_lock_for_immediate_reuse(self) -> None:
        content = b"archive"
        identity = _identity(content)
        response = _Response(
            content,
            status=200,
            headers={"Content-Length": str(len(content))},
            url=identity.url,
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / identity.filename
            with mock.patch(
                "compact_vio.data.archive._open_download_response",
                return_value=(response, ()),
            ):
                first = download_archive(_authorization(identity, target), target)
            with mock.patch("compact_vio.data.archive._open_download_response") as open_response:
                second = download_archive(_authorization(identity, target), target)
            open_response.assert_not_called()
            self.assertEqual(first.sha256, second.sha256)
            self.assertTrue((target.parent / f".{target.name}.acquire.lock").is_file())

    def test_candidate_identity_cannot_authorize_download(self) -> None:
        candidate = load_dataset_archive_candidate(_candidate_path())
        with self.assertRaises(TypeError):
            AuthorizedArchiveAcquisition(  # type: ignore[call-arg]
                identity=candidate.published_identity,
                authorization_record_id="forged",
                authorization_record_sha256="0" * 64,
                destination_path="/tmp/forged.tar",
                reviewed_by="forged",
                reviewed_at="2026-08-28T15:00:00Z",
                _capability=object(),
            )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / candidate.published_identity.filename
            with (
                mock.patch("compact_vio.data.archive._open_download_response") as open_response,
                self.assertRaisesRegex(ArchiveError, "AuthorizedArchiveAcquisition"),
            ):
                download_archive(candidate.published_identity, target)  # type: ignore[arg-type]
            open_response.assert_not_called()

    def test_authorization_is_bound_to_exact_destination_and_approved_record(self) -> None:
        identity = _identity(b"archive")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorized_target = root / identity.filename
            authorization = _authorization(identity, authorized_target)
            other_target = root / "other" / identity.filename
            with (
                mock.patch("compact_vio.data.archive._open_download_response") as open_response,
                self.assertRaisesRegex(ArchiveError, "authorized scope"),
            ):
                download_archive(authorization, other_target)
            open_response.assert_not_called()

            record_path = root / ".synthetic-acquisition-authorization.json"
            record = json.loads(record_path.read_text(encoding="utf-8"))
            record["record_status"] = "candidate_non_executable"
            record_path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ArchiveError, "record_status"):
                load_authorized_archive_acquisition(record_path, identity)

    def test_inode_replacement_between_verification_and_link_is_not_published(self) -> None:
        content = b"verified archive"
        malicious = b"malicious bytes!"
        self.assertEqual(len(content), len(malicious))
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / identity.filename
            partial = target.with_name(f"{target.name}.part")
            response = _Response(
                content,
                status=200,
                headers={"Content-Length": str(len(content))},
                url=identity.url,
            )
            real_link = os.link
            replaced = False

            def racing_link(
                source: os.PathLike[str] | str,
                destination: os.PathLike[str] | str,
                *,
                follow_symlinks: bool = True,
            ) -> None:
                nonlocal replaced
                if not replaced and Path(source) == partial:
                    replaced = True
                    partial.unlink()
                    partial.write_bytes(malicious)
                real_link(source, destination, follow_symlinks=follow_symlinks)

            with (
                mock.patch(
                    "compact_vio.data.archive._open_download_response",
                    return_value=(response, ()),
                ),
                mock.patch("compact_vio.data.archive.os.link", side_effect=racing_link),
                self.assertRaisesRegex(ArchiveError, "changed before verified publication"),
            ):
                download_archive(_authorization(identity, target), target)

            self.assertFalse(target.exists())
            self.assertTrue(replaced)
            self.assertEqual(partial.read_bytes(), malicious)
            self.assertFalse(any(Path(directory).glob(".*.verified-*")))

    def test_same_inode_mutation_after_verification_is_not_published(self) -> None:
        content = b"verified archive"
        malicious = b"malicious bytes!"
        identity = _identity(content)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / identity.filename
            partial = target.with_name(f"{target.name}.part")
            response = _Response(
                content,
                status=200,
                headers={"Content-Length": str(len(content))},
                url=identity.url,
            )
            real_link = os.link
            mutated = False

            def racing_link(
                source: os.PathLike[str] | str,
                destination: os.PathLike[str] | str,
                *,
                follow_symlinks: bool = True,
            ) -> None:
                nonlocal mutated
                if not mutated and Path(source) == partial:
                    mutated = True
                    with partial.open("r+b") as handle:
                        handle.write(malicious)
                        handle.flush()
                        os.fsync(handle.fileno())
                real_link(source, destination, follow_symlinks=follow_symlinks)

            with (
                mock.patch(
                    "compact_vio.data.archive._open_download_response",
                    return_value=(response, ()),
                ),
                mock.patch("compact_vio.data.archive.os.link", side_effect=racing_link),
                self.assertRaisesRegex(ArchiveError, "bytes changed"),
            ):
                download_archive(_authorization(identity, target), target)

            self.assertTrue(mutated)
            self.assertFalse(target.exists())
            self.assertEqual(partial.read_bytes(), malicious)

    def test_download_rejects_unbounded_chunk_size(self) -> None:
        identity = _identity(b"archive")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / identity.filename
            with self.assertRaisesRegex(ArchiveError, "chunk_size"):
                download_archive(
                    _authorization(identity, target),
                    target,
                    chunk_size=17 * 1024 * 1024,
                )


class TarInventoryTests(unittest.TestCase):
    def test_inventory_is_read_only_and_reports_canonical_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar"
            _write_tar(
                archive,
                [
                    _directory("dataset/"),
                    _file("dataset/cam0/data.csv", b"camera"),
                    _file("dataset/imu0/data.csv", b"imu"),
                ],
            )

            inventory = inventory_tar(archive, expected_sha256=_sha256(archive))

            self.assertEqual(inventory.member_count, 3)
            self.assertEqual(inventory.file_count, 2)
            self.assertEqual(inventory.expanded_size_bytes, 9)
            self.assertEqual(inventory.members[1].path, "dataset/cam0/data.csv")
            self.assertEqual(set(root.iterdir()), {archive})

    def test_rejects_unsafe_paths_and_non_regular_types(self) -> None:
        cases: list[tuple[str, tarfile.TarInfo, bytes | None, str]] = []
        for name, expected in (
            ("../escape", "prohibited"),
            ("/absolute", "prohibited"),
            ("root\\escape", "prohibited"),
            ("root/./file", "not canonical"),
            ("root//file", "not canonical"),
        ):
            member, content = _file(name, b"x")
            cases.append((name, member, content, expected))
        for label, member_type, expected in (
            ("symlink", tarfile.SYMTYPE, "symlink"),
            ("hardlink", tarfile.LNKTYPE, "hardlink"),
            ("fifo", tarfile.FIFOTYPE, "FIFO"),
            ("character", tarfile.CHRTYPE, "device"),
            ("block", tarfile.BLKTYPE, "device"),
            ("unknown", b"V", "non-regular"),
            ("sparse", tarfile.GNUTYPE_SPARSE, "sparse"),
        ):
            member = tarfile.TarInfo(f"root/{label}")
            member.type = member_type
            member.size = 0
            cases.append((label, member, None, expected))

        for label, member, content, expected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / "archive.tar"
                _write_tar(archive, [(member, content)])
                with self.assertRaisesRegex(ArchiveError, expected):
                    inventory_tar(archive, expected_sha256=_sha256(archive))

    def test_inventory_requires_pinned_sha_and_uncompressed_tar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar"
            _write_tar(archive, [_file("file", b"data")])
            with self.assertRaisesRegex(ArchiveError, "SHA-256 mismatch"):
                inventory_tar(archive, expected_sha256="0" * 64)
            compressed = root / "archive.tar.gz"
            compressed.write_bytes(archive.read_bytes())
            with self.assertRaisesRegex(ArchiveError, "uncompressed"):
                inventory_tar(compressed, expected_sha256=_sha256(compressed))

    def test_rejects_duplicate_normalized_paths_and_topology_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "duplicate.tar"
            decomposed = "root/cafe\N{COMBINING ACUTE ACCENT}"
            composed = "root/caf\N{LATIN SMALL LETTER E WITH ACUTE}"
            _write_tar(archive, [_file(decomposed, b"a"), _file(composed, b"b")])
            with self.assertRaisesRegex(ArchiveError, "duplicate normalized"):
                inventory_tar(archive, expected_sha256=_sha256(archive))

        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "conflict.tar"
            _write_tar(
                archive,
                [_file("root/child", b"a"), _file("root", b"b")],
            )
            with self.assertRaisesRegex(ArchiveError, "topology conflicts"):
                inventory_tar(archive, expected_sha256=_sha256(archive))

    def test_enforces_member_count_member_size_and_expanded_size_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "archive.tar"
            _write_tar(archive, [_file("one", b"12"), _file("two", b"34")])
            cases = (
                (TarLimits(1, 100, 100), "member count"),
                (TarLimits(10, 1, 100), "member one exceeds size"),
                (TarLimits(10, 100, 3), "expanded size"),
            )
            for limits, expected in cases:
                with self.subTest(limits=limits), self.assertRaisesRegex(ArchiveError, expected):
                    inventory_tar(
                        archive,
                        expected_sha256=_sha256(archive),
                        limits=limits,
                    )


class TarStructuralAuditTests(unittest.TestCase):
    def test_records_inert_links_without_following_or_marking_them_extractable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar"
            symlink = tarfile.TarInfo("dataset/dso/cam1/images")
            symlink.type = tarfile.SYMTYPE
            symlink.linkname = "../../cam0/images"
            hardlink = tarfile.TarInfo("dataset/dso/cam1/times.txt")
            hardlink.type = tarfile.LNKTYPE
            hardlink.linkname = "dataset/dso/cam0/times.txt"
            _write_tar(
                archive,
                [
                    _directory("dataset/"),
                    _file("dataset/mav0/cam0/data.csv", b"camera"),
                    (symlink, None),
                    (hardlink, None),
                ],
            )

            audit = audit_tar_structure(archive, expected_sha256=_sha256(archive))

            self.assertEqual(audit.member_count, 4)
            self.assertEqual(audit.regular_file_count, 1)
            self.assertEqual(audit.non_regular_member_count, 2)
            self.assertEqual(audit.expanded_regular_size_bytes, 6)
            self.assertFalse(audit.strict_extraction_compatible)
            self.assertEqual(audit.members[2].kind, "symlink")
            self.assertEqual(audit.members[2].link_target, "../../cam0/images")
            self.assertEqual(audit.members[3].kind, "hardlink")
            self.assertEqual(set(root.iterdir()), {archive})
            with self.assertRaisesRegex(ArchiveError, "symlink"):
                inventory_tar(archive, expected_sha256=_sha256(archive))

    def test_still_rejects_unsafe_paths_topology_hash_and_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "archive.tar"
            unsafe = tarfile.TarInfo("../escape")
            unsafe.type = tarfile.SYMTYPE
            unsafe.linkname = "/outside"
            _write_tar(archive, [(unsafe, None)])
            with self.assertRaisesRegex(ArchiveError, "traversal"):
                audit_tar_structure(archive, expected_sha256=_sha256(archive))

        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "archive.tar"
            link = tarfile.TarInfo("root")
            link.type = tarfile.SYMTYPE
            link.linkname = "target"
            _write_tar(archive, [(link, None), _file("root/child", b"x")])
            with self.assertRaisesRegex(ArchiveError, "topology conflicts"):
                audit_tar_structure(archive, expected_sha256=_sha256(archive))
            with self.assertRaisesRegex(ArchiveError, "SHA-256 mismatch"):
                audit_tar_structure(archive, expected_sha256="0" * 64)
            with self.assertRaisesRegex(ArchiveError, "member count"):
                audit_tar_structure(
                    archive,
                    expected_sha256=_sha256(archive),
                    limits=TarLimits(1, 100, 100),
                )

    def test_structural_record_contract_rejects_malformed_values(self) -> None:
        with self.assertRaisesRegex(ArchiveError, "kind"):
            TarStructuralMemberRecord("member", [], 0, None)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ArchiveError, "link_target"):
            TarStructuralMemberRecord("member", "symlink", 0, None)
        with self.assertRaisesRegex(ArchiveError, "cannot declare"):
            TarStructuralMemberRecord("member", "file", 0, "target")


class TarExtractionTests(unittest.TestCase):
    def test_extracts_only_exact_allowlist_and_publishes_new_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar"
            _write_tar(
                archive,
                [
                    _file("dataset/selected.txt", b"selected"),
                    _file("dataset/ignored.txt", b"ignored"),
                ],
            )
            expected_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
            output = root / "published"

            report = extract_tar(
                archive,
                output,
                expected_sha256=expected_sha256,
                allowed_files=("dataset/selected.txt",),
                validate_staging=_accept_staging,
            )

            self.assertEqual((output / "dataset/selected.txt").read_bytes(), b"selected")
            self.assertFalse((output / "dataset/ignored.txt").exists())
            self.assertEqual(report.archive_sha256, expected_sha256)
            self.assertEqual(report.expanded_size_bytes, len(b"selected"))
            self.assertEqual(report.extracted_files[0].path, "dataset/selected.txt")
            self.assertEqual(
                report.extracted_files[0].sha256,
                hashlib.sha256(b"selected").hexdigest(),
            )

    def test_requires_pinned_sha_and_canonical_present_regular_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar"
            _write_tar(archive, [_file("dataset/file", b"data")])
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            cases = (
                ("0" * 64, ("dataset/file",), "SHA-256 mismatch"),
                (digest, ("dataset/./file",), "is not canonical"),
                (digest, ("dataset/missing",), "is absent"),
            )
            for index, (expected_sha256, allowlist, expected) in enumerate(cases):
                output = root / f"output-{index}"
                with (
                    self.subTest(expected=expected),
                    self.assertRaisesRegex(ArchiveError, expected),
                ):
                    extract_tar(
                        archive,
                        output,
                        expected_sha256=expected_sha256,
                        allowed_files=allowlist,
                        validate_staging=_accept_staging,
                    )
                self.assertFalse(output.exists())

    def test_validates_unselected_members_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar"
            unsafe = tarfile.TarInfo("unsafe-link")
            unsafe.type = tarfile.SYMTYPE
            unsafe.linkname = "target"
            _write_tar(archive, [_file("selected", b"data"), (unsafe, None)])
            output = root / "output"
            with self.assertRaisesRegex(ArchiveError, "symlink"):
                extract_tar(
                    archive,
                    output,
                    expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                    allowed_files=("selected",),
                    validate_staging=_accept_staging,
                )
            self.assertFalse(output.exists())
            self.assertFalse(any(root.glob(".output.staging-*")))

    def test_refuses_to_overwrite_existing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar"
            _write_tar(archive, [_file("file", b"data")])
            output = root / "output"
            output.mkdir()
            marker = output / "marker"
            marker.write_bytes(b"preserve")
            with self.assertRaisesRegex(ArchiveError, "refusing to overwrite"):
                extract_tar(
                    archive,
                    output,
                    expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                    allowed_files=("file",),
                    validate_staging=_accept_staging,
                )
            self.assertEqual(marker.read_bytes(), b"preserve")

    def test_file_permissions_do_not_enable_archive_control_bits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar"
            member, content = _file("executable", b"data")
            member.mode = stat.S_ISUID | stat.S_ISGID | 0o777
            _write_tar(archive, [(member, content)])
            output = root / "output"
            extract_tar(
                archive,
                output,
                expected_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                allowed_files=("executable",),
                validate_staging=_accept_staging,
            )
            mode = os.stat(output / "executable").st_mode
            self.assertFalse(mode & stat.S_ISUID)
            self.assertFalse(mode & stat.S_ISGID)

    def test_staging_validator_failure_or_mutation_prevents_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar"
            _write_tar(archive, [_file("file", b"data")])
            digest = _sha256(archive)

            def reject(_staging: Path, _receipts: tuple[object, ...]) -> None:
                raise ValueError("semantic mismatch")

            with self.assertRaisesRegex(ArchiveError, "semantic validation failed"):
                extract_tar(
                    archive,
                    root / "rejected",
                    expected_sha256=digest,
                    allowed_files=("file",),
                    validate_staging=reject,
                )
            self.assertFalse((root / "rejected").exists())

            def mutate(staging: Path, _receipts: tuple[object, ...]) -> None:
                (staging / "file").write_bytes(b"evil")

            with self.assertRaisesRegex(ArchiveError, "changed extracted file"):
                extract_tar(
                    archive,
                    root / "mutated",
                    expected_sha256=digest,
                    allowed_files=("file",),
                    validate_staging=mutate,
                )
            self.assertFalse((root / "mutated").exists())


if __name__ == "__main__":
    unittest.main()
