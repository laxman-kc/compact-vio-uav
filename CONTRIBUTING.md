# Contributing

CompactVIO-UAV is a publicly readable research project, but a source license has not been
selected. Public access does not grant permission to copy, modify, or redistribute the source.

Until a source license and contribution terms are selected, external contributions are
**discussion-only**:

- do not send an implementation pull request;
- use issues for reproducible bug reports, documentation feedback, research questions, and scope
  discussion;
- the owner will update this file when external pull requests can be accepted.

## Development setup

CI runs on Python 3.10 and 3.12. A local environment with the demo, ONNX, schema-validation, and
development tools can be installed with:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[demo,onnx,governance,dev]'
```

The `dev` extra pins Ruff to the same `0.16.4` version used by CI.

## Checks

The checked-in [CI workflow](.github/workflows/ci.yml) is authoritative. Its local checks are:

```bash
python -m compileall -q src tests scripts
python examples/create_example_bundle.py --output /tmp/compact-vio-example.zip
python -m unittest discover -s tests -v

compact-vio-artifacts --help
compact-vio-acquire-archive --help
compact-vio-audit-archive-structure --help
compact-vio-extract-regular-slice --help
compact-vio-inspect-tumvi-format --help
compact-vio-copy-audit --help
compact-vio-evaluate-trajectory --help
compact-vio-export-onnx --help
compact-vio-run --help
compact-vio-demo --help
compact-vio-repo-check .

ruff check .
ruff format --check .
python scripts/validate_schemas.py
```

CI also verifies that root scratch directories are ignored without accidentally ignoring source
or governed data:

```bash
git check-ignore --no-index data/example.bin
git check-ignore --no-index checkpoints/example.pt
if git check-ignore --no-index governance/data/example.yaml; then exit 1; fi
if git check-ignore --no-index src/compact_vio/data/example.py; then exit 1; fi
```

CI also confirms that a normal preflight stops in its expected blocked state when no durable
artifact configuration is supplied:

```bash
python - <<'PY'
import json
import subprocess

result = subprocess.run(
    ["compact-vio-preflight"],
    check=False,
    capture_output=True,
    text=True,
)
assert result.returncode == 1, result.stderr
report = json.loads(result.stdout)
assert report["assessment"] == "blocked"
assert report["artifact_restore_gate_passed"] is False
PY
```

For user-facing changes, also run the local web app and verify the built-in example, recording
bundle upload, result explanation, chart, and downloads at desktop and narrow viewport widths.

## Maintainer pull-request expectations

- Link the issue containing the prior scope and contribution-terms discussion.
- Keep the public README and current architecture focused on the runnable product.
- Put dated metrics, hashes, and experimental evidence in `reports/`.
- Do not claim model accuracy from software execution alone.
- Do not add datasets, credentials, trained weights, or third-party binaries to Git.
- Add focused tests for new parsing, inference, reporting, or UI behavior.
- Report every check run and any check that could not be run.
