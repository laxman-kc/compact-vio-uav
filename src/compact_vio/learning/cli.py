"""Command line execution of the EuRoC compact learned-VIO vertical slice."""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from compact_vio.data.euroc import (
    EuRoCDataError,
    EuRoCSequence,
    SequenceSplits,
    calibration_sources_sha256,
    load_euroc_sequence,
    sequence_sources_sha256,
    sha256_file,
    validate_sequence_splits,
)
from compact_vio.evaluation.se3 import (
    RelativePoseIncrement,
    Se3EvaluationError,
    evaluate_relative_pose_sequence,
    zero_motion_baseline,
)
from compact_vio.learning.config import TrainingConfig
from compact_vio.learning.errors import LearningDependencyError, LearningError

_SMOKE_TRAIN_SAMPLES = 128
_SMOKE_EVALUATION_SAMPLES = 64
_SMOKE_EPOCHS = 2


@dataclass(frozen=True, slots=True)
class ArchiveIdentity:
    """Checked-in source archive identity used by one or more sequences."""

    archive_id: str
    sha256: str
    sequences: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunSpec:
    """Validated experiment configuration plus its disjoint split manifest."""

    experiment_id: str
    config_path: Path
    config_sha256: str
    split_path: Path
    split_sha256: str
    dataset_doi: str
    training: TrainingConfig
    training_frame_strides: tuple[int, ...]
    splits: SequenceSplits
    integration_only: tuple[str, ...]
    archives: tuple[ArchiveIdentity, ...]

    def archive_sha256_by_sequence(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for archive in self.archives:
            for sequence_id in archive.sequences:
                if sequence_id in result:
                    raise LearningError(
                        f"sequence {sequence_id!r} appears in more than one source archive"
                    )
                result[sequence_id] = archive.sha256
        return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, *, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LearningError(f"cannot read {field} {path}: {exc}") from exc
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise LearningError(f"{field} must be a JSON object with string keys")
    return value


def _exact_object(value: object, fields: set[str], *, field: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise LearningError(f"{field} must contain exact fields {sorted(fields)!r}")
    return value


def _text(value: object, *, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise LearningError(f"{field} must be a non-empty string")
    return value


def _sha256(value: object, *, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise LearningError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _string_array(value: object, *, field: str, allow_empty: bool = False) -> tuple[str, ...]:
    if type(value) is not list or (not value and not allow_empty):
        raise LearningError(f"{field} must be a {'possibly empty ' if allow_empty else ''}array")
    result = tuple(_text(item, field=f"{field} item") for item in value)
    if len(result) != len(set(result)):
        raise LearningError(f"{field} must not contain duplicates")
    return result


def _resolve_declared_path(config_path: Path, declared: str) -> Path:
    supplied = Path(declared)
    if supplied.is_absolute():
        if not supplied.is_file():
            raise LearningError(f"declared split manifest does not exist: {supplied}")
        return supplied.resolve()
    matches: list[Path] = []
    for base in (Path.cwd(), *config_path.resolve().parents):
        candidate = (base / supplied).resolve()
        if candidate.is_file() and candidate not in matches:
            matches.append(candidate)
    if not matches:
        raise LearningError(
            f"cannot resolve split manifest {declared!r} from the current directory "
            f"or ancestors of {config_path}"
        )
    if len(matches) > 1:
        raise LearningError(f"declared split manifest is ambiguous: {matches!r}")
    return matches[0]


def _parse_split_manifest(
    path: Path,
) -> tuple[str, SequenceSplits, tuple[str, ...], tuple[ArchiveIdentity, ...]]:
    document = _read_json(path, field="split manifest")
    required = {
        "record_type",
        "schema_version",
        "dataset",
        "archives",
        "development_split",
        "modalities",
        "label_source",
        "notes",
    }
    if set(document) != required:
        raise LearningError("split manifest has unexpected or missing top-level fields")
    if document["record_type"] != "euroc_acquisition_plan":
        raise LearningError("split record_type must equal euroc_acquisition_plan")
    if document["schema_version"] != "1.0.0":
        raise LearningError("unsupported split manifest schema_version")
    dataset = _exact_object(
        document["dataset"],
        {"title", "doi", "landing_page", "rights_statement", "publisher"},
        field="dataset",
    )
    doi = _text(dataset["doi"], field="dataset.doi")
    archives_value = document["archives"]
    if type(archives_value) is not list or not archives_value:
        raise LearningError("archives must be a non-empty array")
    archives: list[ArchiveIdentity] = []
    archive_ids: set[str] = set()
    declared_sequence_ids: set[str] = set()
    archive_fields = {
        "archive_id",
        "filename",
        "url",
        "size_bytes",
        "md5",
        "sha256",
        "sequences",
    }
    for index, value in enumerate(archives_value):
        archive = _exact_object(value, archive_fields, field=f"archives[{index}]")
        archive_id = _text(archive["archive_id"], field=f"archives[{index}].archive_id")
        if archive_id in archive_ids:
            raise LearningError(f"duplicate archive_id {archive_id!r}")
        archive_ids.add(archive_id)
        sequence_ids = _string_array(archive["sequences"], field=f"archives[{index}].sequences")
        duplicate_sequences = declared_sequence_ids & set(sequence_ids)
        if duplicate_sequences:
            raise LearningError(
                f"sequences occur in multiple archives: {sorted(duplicate_sequences)!r}"
            )
        declared_sequence_ids.update(sequence_ids)
        archives.append(
            ArchiveIdentity(
                archive_id=archive_id,
                sha256=_sha256(archive["sha256"], field=f"archives[{index}].sha256"),
                sequences=sequence_ids,
            )
        )
    split = _exact_object(
        document["development_split"],
        {"integration_only", "train", "validation", "test"},
        field="development_split",
    )
    integration_only = _string_array(
        split["integration_only"], field="development_split.integration_only", allow_empty=True
    )
    splits = validate_sequence_splits(
        train=_string_array(split["train"], field="development_split.train"),
        validation=_string_array(split["validation"], field="development_split.validation"),
        test=_string_array(split["test"], field="development_split.test"),
    )
    selected = (*integration_only, *splits.train, *splits.validation, *splits.test)
    if len(selected) != len(set(selected)):
        raise LearningError("integration/train/validation/test sequence groups must be disjoint")
    missing = set(selected) - declared_sequence_ids
    if missing:
        raise LearningError(
            f"split sequences are absent from archive declarations: {sorted(missing)!r}"
        )
    if document["label_source"] != "state_groundtruth_estimate0":
        raise LearningError("V1 label_source must equal state_groundtruth_estimate0")
    modalities = _string_array(document["modalities"], field="modalities")
    required_modalities = {
        "cam0_grayscale",
        "imu0_gyroscope",
        "imu0_accelerometer",
    }
    if set(modalities) != required_modalities:
        raise LearningError("V1 modalities must be cam0 grayscale plus imu0 gyro/accelerometer")
    return doi, splits, integration_only, tuple(archives)


def load_run_spec(config_path: os.PathLike[str] | str) -> RunSpec:
    """Load and bind the exact checked-in experiment and split records."""

    supplied = Path(config_path)
    if not supplied.is_file() or supplied.is_symlink():
        raise LearningError(f"config must be a regular non-symlink file: {supplied}")
    config = supplied.resolve()
    document = _read_json(config, field="experiment config")
    training = TrainingConfig.from_mapping(document)
    sampling = document.get("sampling")
    if type(sampling) is not dict:
        raise LearningError("sampling must be a JSON object")
    if "frame_strides" in sampling:
        training_frame_strides = tuple(sampling["frame_strides"])
    else:
        training_frame_strides = (sampling.get("frame_stride"),)
    experiment_id = _text(document.get("experiment_id"), field="experiment_id")
    split_declared = _text(document.get("split_manifest"), field="split_manifest")
    split_path = _resolve_declared_path(config, split_declared)
    doi, splits, integration_only, archives = _parse_split_manifest(split_path)
    return RunSpec(
        experiment_id=experiment_id,
        config_path=config,
        config_sha256=sha256_file(config),
        split_path=split_path,
        split_sha256=sha256_file(split_path),
        dataset_doi=doi,
        training=training,
        training_frame_strides=training_frame_strides,  # type: ignore[arg-type]
        splits=splits,
        integration_only=integration_only,
        archives=archives,
    )


def _prepare_output_directory(path: os.PathLike[str] | str) -> Path:
    destination = Path(path)
    if destination.is_symlink():
        raise LearningError(f"output directory must not be a symlink: {destination}")
    if destination.exists():
        if not destination.is_dir():
            raise LearningError(f"output path exists and is not a directory: {destination}")
        try:
            if any(destination.iterdir()):
                raise LearningError(f"refusing non-empty output directory: {destination}")
        except OSError as exc:
            raise LearningError(f"cannot inspect output directory {destination}: {exc}") from exc
    else:
        try:
            destination.mkdir(parents=True)
        except OSError as exc:
            raise LearningError(f"cannot create output directory {destination}: {exc}") from exc
    return destination.resolve()


def _write_json(path: Path, value: object) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except (OSError, TypeError, ValueError) as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise LearningError(f"cannot write JSON artifact {path}: {exc}") from exc


def _git_revision(config_path: Path) -> str:
    repository: Path | None = None
    for parent in (config_path.parent, *config_path.parents):
        if (parent / ".git").exists():
            repository = parent
            break
    if repository is None:
        raise LearningError(f"cannot identify Git repository containing {config_path}")
    try:
        revision = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repository), "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise LearningError(f"cannot capture Git revision: {exc}") from exc
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise LearningError("Git returned an invalid full revision")
    return f"{revision}-dirty" if dirty else revision


def _seed_worker(worker_id: int) -> None:
    del worker_id
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - worker requires training extra
        raise LearningDependencyError("PyTorch is required in DataLoader workers") from exc
    worker_seed = torch.initial_seed() % (2**32)
    random.seed(worker_seed)


def _load_declared_sequences(
    data_root: Path, sequence_ids: Sequence[str]
) -> tuple[EuRoCSequence, ...]:
    if not data_root.is_dir() or data_root.is_symlink():
        raise LearningError(f"data root must be a regular directory: {data_root}")
    sequences: list[EuRoCSequence] = []
    for sequence_id in sequence_ids:
        sequences.append(load_euroc_sequence(data_root / sequence_id))
    return tuple(sequences)


def _select_device(torch: Any, requested: str) -> Any:
    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise LearningError("CUDA was requested but torch.cuda.is_available() is false")
    return torch.device(requested)


def _history_json(result: Any) -> list[dict[str, object]]:
    return [
        {
            "epoch": index,
            "train": asdict(train),
            "validation": asdict(validation),
        }
        for index, (train, validation) in enumerate(
            zip(result.train_history, result.validation_history, strict=True), start=1
        )
    ]


def _runtime_training_config(config: TrainingConfig, *, smoke: bool) -> TrainingConfig:
    if type(smoke) is not bool:
        raise LearningError("smoke must be boolean")
    return replace(config, epochs=_SMOKE_EPOCHS) if smoke else config


def _bounded_subset_indices(sample_count: int, maximum_samples: int) -> tuple[int, ...]:
    """Select a deterministic, sequence-wide smoke subset without prefix bias."""

    if type(sample_count) is not int or sample_count <= 0:
        raise LearningError("sample_count must be a positive integer")
    if type(maximum_samples) is not int or maximum_samples <= 0:
        raise LearningError("maximum_samples must be a positive integer")
    if sample_count <= maximum_samples:
        return tuple(range(sample_count))
    if maximum_samples == 1:
        return (0,)
    return tuple(
        index * (sample_count - 1) // (maximum_samples - 1) for index in range(maximum_samples)
    )


def _empirical_percentile(values: Sequence[float], percentile: float) -> float:
    """Return a nearest-rank percentile for a nonempty finite sample."""

    if not values or any(type(value) is not float or not math.isfinite(value) for value in values):
        raise LearningError("percentile values must be nonempty finite floats")
    if type(percentile) is not float or not 0.0 <= percentile <= 1.0:
        raise LearningError("percentile must be a float in [0, 1]")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _write_predictions_and_metrics(
    *,
    model: Any,
    sequences: Sequence[EuRoCSequence],
    config: TrainingConfig,
    device: Any,
    output_path: Path,
    data_loader_type: Any,
    dataset_type: Any,
    collate: Any,
    predict: Any,
    subset_type: Any,
    torch_module: Any,
    maximum_samples: int | None = None,
) -> dict[str, object]:
    sequence_results: dict[str, object] = {}
    try:
        output_handle = output_path.open("x", encoding="utf-8")
    except OSError as exc:
        raise LearningError(f"cannot create predictions artifact {output_path}: {exc}") from exc
    with output_handle:
        for sequence in sequences:
            dataset = dataset_type(
                (sequence,),
                model_config=config.model,
                data_config=config.data,
                frame_strides=(1,),
            )
            eligible_pair_count = len(dataset)
            if maximum_samples is not None:
                dataset = subset_type(
                    dataset,
                    _bounded_subset_indices(len(dataset), maximum_samples),
                )
            selected_pair_count = len(dataset)
            loader = data_loader_type(
                dataset,
                batch_size=config.batch_size,
                shuffle=False,
                num_workers=config.num_workers,
                collate_fn=collate,
                pin_memory=device.type == "cuda",
                persistent_workers=config.num_workers > 0,
            )
            reference: list[RelativePoseIncrement] = []
            predicted: list[RelativePoseIncrement] = []
            batch_latencies_seconds: list[float] = []
            translation_squared_error = 0.0
            rotation_squared_error = 0.0
            sample_count = 0
            model.zero_grad(set_to_none=True)
            if device.type == "cuda":
                torch_module.cuda.empty_cache()
                torch_module.cuda.reset_peak_memory_stats(device)
            for batch in loader:
                if device.type == "cuda":
                    torch_module.cuda.synchronize(device)
                inference_started = time.perf_counter()
                prediction = predict(model, batch, device=device).motion_vectors
                if device.type == "cuda":
                    torch_module.cuda.synchronize(device)
                batch_latencies_seconds.append(time.perf_counter() - inference_started)
                truth = batch.target_motion.detach().to(device="cpu")
                error = prediction - truth
                translation_squared_error += float(error[:, :3].square().sum())
                rotation_squared_error += float(error[:, 3:].square().sum())
                sample_count += prediction.shape[0]
                for row, identity in enumerate(batch.identities):
                    sample_id = f"{identity.previous_timestamp_ns}:{identity.current_timestamp_ns}"
                    truth_values = tuple(float(value) for value in truth[row].tolist())
                    predicted_values = tuple(float(value) for value in prediction[row].tolist())
                    reference_increment = RelativePoseIncrement(
                        sequence_id=identity.sequence_id,
                        sample_id=sample_id,
                        start_timestamp_ns=identity.previous_timestamp_ns,
                        end_timestamp_ns=identity.current_timestamp_ns,
                        translation_previous_body_m=truth_values[:3],  # type: ignore[arg-type]
                        rotation_vector_previous_to_current_rad=truth_values[3:],  # type: ignore[arg-type]
                    )
                    predicted_increment = RelativePoseIncrement(
                        sequence_id=identity.sequence_id,
                        sample_id=sample_id,
                        start_timestamp_ns=identity.previous_timestamp_ns,
                        end_timestamp_ns=identity.current_timestamp_ns,
                        translation_previous_body_m=predicted_values[:3],  # type: ignore[arg-type]
                        rotation_vector_previous_to_current_rad=predicted_values[3:],  # type: ignore[arg-type]
                    )
                    reference.append(reference_increment)
                    predicted.append(predicted_increment)
                    json.dump(
                        {
                            "sequence_id": identity.sequence_id,
                            "previous_timestamp_ns": identity.previous_timestamp_ns,
                            "current_timestamp_ns": identity.current_timestamp_ns,
                            "prediction": {
                                "translation_previous_body_m": list(predicted_values[:3]),
                                "rotation_vector_previous_to_current_rad": list(
                                    predicted_values[3:]
                                ),
                            },
                            "reference": {
                                "translation_previous_body_m": list(truth_values[:3]),
                                "rotation_vector_previous_to_current_rad": list(truth_values[3:]),
                            },
                        },
                        output_handle,
                        sort_keys=True,
                        allow_nan=False,
                    )
                    output_handle.write("\n")
            if sample_count <= 0:
                raise LearningError(f"test sequence {sequence.sequence_id!r} yielded no samples")
            metrics = evaluate_relative_pose_sequence(tuple(reference), tuple(predicted))
            zero_metrics = zero_motion_baseline(tuple(reference))
            inference_seconds = math.fsum(batch_latencies_seconds)
            sequence_results[sequence.sequence_id] = {
                "pair_translation_rmse_m": math.sqrt(translation_squared_error / sample_count),
                "pair_rotation_rmse_rad": math.sqrt(rotation_squared_error / sample_count),
                "se3": asdict(metrics),
                "zero_motion_se3": asdict(zero_metrics),
                "coverage": {
                    "eligible_pair_count": eligible_pair_count,
                    "selected_pair_count": selected_pair_count,
                    "produced_pair_count": sample_count,
                    "produced_fraction_of_selected": sample_count / selected_pair_count,
                },
                "inference": {
                    "scope": (
                        "predict-batch-model-placement-eval-host-to-device-forward-"
                        "and-device-to-host"
                    ),
                    "dedicated_warmup_batch_count": 0,
                    "batch_count": len(batch_latencies_seconds),
                    "total_seconds": inference_seconds,
                    "pairs_per_second": sample_count / inference_seconds,
                    "batch_latency_p50_ms": 1000.0
                    * _empirical_percentile(batch_latencies_seconds, 0.5),
                    "batch_latency_p95_ms": 1000.0
                    * _empirical_percentile(batch_latencies_seconds, 0.95),
                    "cuda_peak_allocated_bytes": (
                        torch_module.cuda.max_memory_allocated(device)
                        if device.type == "cuda"
                        else None
                    ),
                    "cuda_peak_reserved_bytes": (
                        torch_module.cuda.max_memory_reserved(device)
                        if device.type == "cuda"
                        else None
                    ),
                },
            }
        try:
            output_handle.flush()
            os.fsync(output_handle.fileno())
        except OSError as exc:
            raise LearningError(f"cannot finalize predictions artifact: {exc}") from exc
    return sequence_results


def _run(args: argparse.Namespace) -> int:
    try:
        import torch
        from torch.utils.data import DataLoader, Subset

        from compact_vio.learning.checkpoint import (
            CheckpointProvenance,
            load_checkpoint,
        )
        from compact_vio.learning.dataset import EuRoCPairDataset, collate_vio_batch
        from compact_vio.learning.inference import predict_batch
        from compact_vio.learning.model import CompactVIO
        from compact_vio.learning.training import fit, seed_everything
    except ImportError as exc:
        raise LearningDependencyError(
            "training requires the project train extra (PyTorch, Pillow, and PyYAML)"
        ) from exc

    started_at = _utc_now()
    started_monotonic = time.monotonic()
    spec = load_run_spec(args.config)
    runtime_config = _runtime_training_config(spec.training, smoke=args.smoke)
    output = _prepare_output_directory(args.output_dir)
    data_root = Path(args.data_root).resolve()
    device = _select_device(torch, args.device)
    seed_everything(runtime_config.seed, deterministic=runtime_config.deterministic)
    train_sequences = _load_declared_sequences(data_root, spec.splits.train)
    validation_sequences = _load_declared_sequences(data_root, spec.splits.validation)
    test_sequences = _load_declared_sequences(data_root, spec.splits.test)
    all_sequences = (*train_sequences, *validation_sequences, *test_sequences)

    dataset = EuRoCPairDataset
    train_dataset = dataset(
        train_sequences,
        model_config=runtime_config.model,
        data_config=runtime_config.data,
        frame_strides=spec.training_frame_strides,
    )
    validation_dataset = dataset(
        validation_sequences,
        model_config=runtime_config.model,
        data_config=runtime_config.data,
        frame_strides=spec.training_frame_strides,
    )
    if args.smoke:
        train_dataset = Subset(
            train_dataset,
            _bounded_subset_indices(len(train_dataset), _SMOKE_TRAIN_SAMPLES),
        )
        validation_dataset = Subset(
            validation_dataset,
            _bounded_subset_indices(len(validation_dataset), _SMOKE_EVALUATION_SAMPLES),
        )
    generator = torch.Generator()
    generator.manual_seed(runtime_config.seed)
    loader_options = {
        "batch_size": runtime_config.batch_size,
        "num_workers": runtime_config.num_workers,
        "collate_fn": collate_vio_batch,
        "pin_memory": device.type == "cuda",
        "persistent_workers": runtime_config.num_workers > 0,
        "worker_init_fn": _seed_worker,
    }
    train_loader = DataLoader(
        train_dataset,
        shuffle=True,
        generator=generator,
        **loader_options,
    )
    validation_loader = DataLoader(
        validation_dataset,
        shuffle=False,
        **loader_options,
    )
    archive_hash_by_sequence = spec.archive_sha256_by_sequence()
    calibration_hashes = {
        sequence.sequence_id: calibration_sources_sha256(sequence.root)
        for sequence in all_sequences
    }
    source_hashes = {
        sequence.sequence_id: sequence_sources_sha256(sequence.root) for sequence in all_sequences
    }
    provenance = CheckpointProvenance.create(
        dataset_id=f"EuRoC DOI {spec.dataset_doi}",
        split_id=(
            f"{spec.experiment_id}:config={spec.config_sha256}:"
            f"split={spec.split_sha256}:"
            f"strides={','.join(str(stride) for stride in spec.training_frame_strides)}:"
            f"mode={'smoke' if args.smoke else 'full'}"
        ),
        train_sequence_ids=spec.splits.train,
        validation_sequence_ids=spec.splits.validation,
        source_sha256=source_hashes,
        calibration_sha256=calibration_hashes,
        code_revision=_git_revision(spec.config_path),
    )
    model = CompactVIO(runtime_config.model)
    checkpoint_path = output / "checkpoint.pt"

    def report_progress(epoch: int, train: Any, validation: Any) -> None:
        print(
            json.dumps(
                {
                    "event": "epoch_complete",
                    "epoch": epoch,
                    "train": asdict(train),
                    "validation": asdict(validation),
                },
                sort_keys=True,
                allow_nan=False,
            ),
            flush=True,
        )

    fit_result = fit(
        model,
        train_loader,
        validation_loader,
        device=device,
        config=runtime_config,
        checkpoint_path=checkpoint_path,
        provenance=provenance,
        progress_callback=report_progress,
    )
    best_metadata = load_checkpoint(checkpoint_path, model=model, map_location=device)
    history = _history_json(fit_result)
    history_path = output / "training-history.json"
    _write_json(history_path, history)
    predictions_path = output / "test-predictions.jsonl"
    test_metrics = _write_predictions_and_metrics(
        model=model,
        sequences=test_sequences,
        config=runtime_config,
        device=device,
        output_path=predictions_path,
        data_loader_type=DataLoader,
        dataset_type=EuRoCPairDataset,
        collate=collate_vio_batch,
        predict=predict_batch,
        subset_type=Subset,
        torch_module=torch,
        maximum_samples=_SMOKE_EVALUATION_SAMPLES if args.smoke else None,
    )
    test_metrics_path = output / "test-metrics.json"
    _write_json(test_metrics_path, test_metrics)
    checkpoint_sha256 = sha256_file(checkpoint_path)
    summary = {
        "schema_version": "1.0.0",
        "status": "completed",
        "experiment_id": spec.experiment_id,
        "execution_mode": "smoke" if args.smoke else "full",
        "training_frame_strides": list(spec.training_frame_strides),
        "runtime_config": runtime_config.to_dict(),
        "started_at": started_at,
        "completed_at": _utc_now(),
        "duration_seconds": time.monotonic() - started_monotonic,
        "device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "model_parameter_count": model.parameter_count,
        "config": {"path": str(spec.config_path), "sha256": spec.config_sha256},
        "split_manifest": {"path": str(spec.split_path), "sha256": spec.split_sha256},
        "dataset": {
            "doi": spec.dataset_doi,
            "train": list(spec.splits.train),
            "validation": list(spec.splits.validation),
            "test": list(spec.splits.test),
            "archive_sha256_by_sequence": {
                sequence.sequence_id: archive_hash_by_sequence[sequence.sequence_id]
                for sequence in all_sequences
            },
            "sequence_sources_sha256": source_hashes,
            "calibration_sha256_by_sequence": calibration_hashes,
        },
        "git_revision": provenance.code_revision,
        "best_epoch": best_metadata.epoch,
        "best_validation_metrics": best_metadata.metrics,
        "artifacts": {
            "checkpoint": checkpoint_path.name,
            "checkpoint_sha256": checkpoint_sha256,
            "training_history": history_path.name,
            "test_metrics": test_metrics_path.name,
            "test_predictions": predictions_path.name,
        },
        "test_metrics": test_metrics,
    }
    summary_path = output / "run-summary.json"
    _write_json(summary_path, summary)
    print(
        json.dumps(
            {
                "event": "run_complete",
                "summary": str(summary_path),
                "checkpoint": str(checkpoint_path),
                "checkpoint_sha256": checkpoint_sha256,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-train",
        description="Train and evaluate the compact EuRoC visual-inertial model.",
    )
    parser.add_argument("--config", required=True, help="V1 experiment JSON configuration")
    parser.add_argument(
        "--data-root",
        required=True,
        help="directory containing extracted EuRoC sequence directories",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="new or empty run-artifact directory",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
        help="execution device (default: auto)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run 2 epochs on at most 128 train and 64 validation/test pairs",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except (LearningError, EuRoCDataError, Se3EvaluationError, OSError, RuntimeError) as exc:
        print(
            json.dumps(
                {"event": "run_failed", "error_type": type(exc).__name__, "error": str(exc)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["RunSpec", "build_parser", "load_run_spec", "main"]
