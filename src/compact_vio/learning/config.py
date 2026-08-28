"""Strict, serializable configuration for compact EuRoC training."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from compact_vio.learning.errors import LearningError


def _positive_integer(value: object, *, field: str) -> None:
    if type(value) is not int or value <= 0:
        raise LearningError(f"{field} must be a positive integer")


def _non_negative_integer(value: object, *, field: str) -> None:
    if type(value) is not int or value < 0:
        raise LearningError(f"{field} must be a non-negative integer")


def _positive_float(value: object, *, field: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or value <= 0:
        raise LearningError(f"{field} must be a finite positive number")


def _non_negative_float(value: object, *, field: str) -> None:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or value < 0:
        raise LearningError(f"{field} must be a finite non-negative number")


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Dimensions of the compact frame-pair, temporal IMU, and gated-fusion model."""

    image_height_px: int = 192
    image_width_px: int = 320
    visual_feature_dim: int = 256
    imu_hidden_dim: int = 96
    fusion_hidden_dim: int = 256
    dropout_probability: float = 0.1
    rotation_state_source: str = "shared-recurrent-fusion-state/v1"

    def __post_init__(self) -> None:
        for field in (
            "image_height_px",
            "image_width_px",
            "visual_feature_dim",
            "imu_hidden_dim",
            "fusion_hidden_dim",
        ):
            _positive_integer(getattr(self, field), field=field)
        _non_negative_float(self.dropout_probability, field="dropout_probability")
        if self.dropout_probability >= 1.0:
            raise LearningError("dropout_probability must be less than one")
        if type(self.rotation_state_source) is not str or self.rotation_state_source not in {
            "shared-recurrent-fusion-state/v1",
            "current-pair-zero-initialized-fusion-state/v1",
        }:
            raise LearningError(
                "rotation_state_source must identify a supported rotation-state policy"
            )


@dataclass(frozen=True, slots=True)
class DataConfig:
    """Input normalization applied identically in training and inference."""

    image_mean: float = 0.5
    image_std: float = 0.25
    gyroscope_scale_rad_s: float = 5.0
    accelerometer_scale_m_s2: float = 20.0

    def __post_init__(self) -> None:
        if (
            type(self.image_mean) not in (int, float)
            or not math.isfinite(float(self.image_mean))
            or not 0.0 <= self.image_mean <= 1.0
        ):
            raise LearningError("image_mean must be finite and in [0, 1]")
        _positive_float(self.image_std, field="image_std")
        _positive_float(self.gyroscope_scale_rad_s, field="gyroscope_scale_rad_s")
        _positive_float(self.accelerometer_scale_m_s2, field="accelerometer_scale_m_s2")


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    """Optimization and reproducibility settings for one training run."""

    model: ModelConfig = ModelConfig()
    data: DataConfig = DataConfig()
    batch_size: int = 32
    epochs: int = 20
    learning_rate: float = 3e-4
    weight_decay: float = 1e-4
    translation_loss_weight: float = 1.0
    rotation_loss_weight: float = 10.0
    gradient_clip_norm: float = 1.0
    num_workers: int = 4
    seed: int = 7
    use_amp: bool = True
    deterministic: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.model, ModelConfig):
            raise LearningError("model must be a ModelConfig")
        if not isinstance(self.data, DataConfig):
            raise LearningError("data must be a DataConfig")
        for field in ("batch_size", "epochs"):
            _positive_integer(getattr(self, field), field=field)
        for field in (
            "learning_rate",
            "translation_loss_weight",
            "rotation_loss_weight",
            "gradient_clip_norm",
        ):
            _positive_float(getattr(self, field), field=field)
        _non_negative_float(self.weight_decay, field="weight_decay")
        _non_negative_integer(self.num_workers, field="num_workers")
        _non_negative_integer(self.seed, field="seed")
        if type(self.use_amp) is not bool or type(self.deterministic) is not bool:
            raise LearningError("use_amp and deterministic must be boolean")

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-compatible configuration mapping."""

        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TrainingConfig:
        """Parse an exact configuration mapping and reject unknown fields."""

        if not isinstance(value, Mapping) or not all(type(key) is str for key in value):
            raise LearningError("training configuration must be a string-keyed mapping")
        allowed = {
            "model",
            "data",
            "batch_size",
            "epochs",
            "learning_rate",
            "weight_decay",
            "translation_loss_weight",
            "rotation_loss_weight",
            "gradient_clip_norm",
            "num_workers",
            "seed",
            "use_amp",
            "deterministic",
        }
        unknown = set(value) - allowed
        if unknown:
            raise LearningError(f"unknown training configuration fields: {sorted(unknown)!r}")
        fields = dict(value)
        model_value = fields.get("model", {})
        if not isinstance(model_value, Mapping):
            raise LearningError("model configuration must be a mapping")
        model_allowed = {
            "image_height_px",
            "image_width_px",
            "visual_feature_dim",
            "imu_hidden_dim",
            "fusion_hidden_dim",
            "dropout_probability",
            "rotation_state_source",
        }
        model_unknown = set(model_value) - model_allowed
        if model_unknown:
            raise LearningError(f"unknown model configuration fields: {sorted(model_unknown)!r}")
        fields["model"] = ModelConfig(**dict(model_value))
        data_value = fields.get("data", {})
        if not isinstance(data_value, Mapping):
            raise LearningError("data configuration must be a mapping")
        data_allowed = {
            "image_mean",
            "image_std",
            "gyroscope_scale_rad_s",
            "accelerometer_scale_m_s2",
        }
        data_unknown = set(data_value) - data_allowed
        if data_unknown:
            raise LearningError(f"unknown data configuration fields: {sorted(data_unknown)!r}")
        fields["data"] = DataConfig(**dict(data_value))
        try:
            return cls(**fields)
        except TypeError as exc:
            raise LearningError(f"invalid training configuration: {exc}") from exc

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> TrainingConfig:
        """Parse either canonical checkpoint fields or the V1 experiment record.

        The experiment record separates image, model, optimization, sampling,
        and selection concerns for a human-facing checked-in configuration. The
        resulting object is the single canonical runtime/checkpoint shape.
        """

        if not isinstance(value, Mapping):
            raise LearningError("training configuration must be a mapping")
        if "schema_version" not in value:
            return cls.from_dict(value)
        required = {
            "schema_version",
            "experiment_id",
            "seed",
            "split_manifest",
            "image",
            "model",
            "optimization",
            "sampling",
            "selection",
        }
        if set(value) != required:
            raise LearningError(
                "V1 experiment configuration must contain the exact declared top-level fields"
            )
        for field in ("schema_version", "experiment_id", "split_manifest"):
            field_value = value[field]
            if type(field_value) is not str or not field_value.strip():
                raise LearningError(f"{field} must be a non-empty string")
        if value["schema_version"] != "1.0.0":
            raise LearningError("unsupported experiment schema_version")
        image = _exact_mapping(
            value["image"], {"width_px", "height_px", "mean", "std"}, field="image"
        )
        model_fields = {
            "visual_feature_dim",
            "imu_hidden_dim",
            "fusion_hidden_dim",
            "dropout",
            "gyro_scale_rad_s",
            "acceleration_scale_m_s2",
        }
        model_value = value["model"]
        if not isinstance(model_value, Mapping) or set(model_value) not in (
            model_fields,
            model_fields | {"rotation_state_source"},
        ):
            raise LearningError(
                "model must contain the exact legacy fields and optional rotation_state_source"
            )
        model = model_value
        optimization = _exact_mapping(
            value["optimization"],
            {
                "epochs",
                "batch_size",
                "learning_rate",
                "weight_decay",
                "translation_loss_weight",
                "rotation_loss_weight",
                "gradient_clip_norm",
                "num_workers",
                "amp",
            },
            field="optimization",
        )
        sampling_value = value["sampling"]
        if not isinstance(sampling_value, Mapping):
            raise LearningError("sampling must be a mapping")
        if set(sampling_value) == {"frame_stride", "max_pairs_per_sequence"}:
            sampling = sampling_value
            if sampling["frame_stride"] != 1:
                raise LearningError("V1 frame_stride must equal one")
        elif set(sampling_value) in (
            {"frame_strides", "max_pairs_per_sequence"},
            {"frame_strides", "max_pairs_per_sequence", "unroll_pairs"},
        ):
            sampling = sampling_value
            strides = sampling["frame_strides"]
            if (
                type(strides) is not list
                or not strides
                or any(type(item) is not int or item <= 0 for item in strides)
                or len(strides) != len(set(strides))
            ):
                raise LearningError("frame_strides must contain unique positive integers")
            unroll_pairs = sampling.get("unroll_pairs", 1)
            if type(unroll_pairs) is not int or unroll_pairs <= 0:
                raise LearningError("unroll_pairs must be a positive integer")
        else:
            raise LearningError(
                "sampling must declare frame_stride or frame_strides plus max_pairs_per_sequence"
            )
        selection = _exact_mapping(value["selection"], {"metric", "mode"}, field="selection")
        maximum = sampling["max_pairs_per_sequence"]
        if maximum is not None and (type(maximum) is not int or maximum <= 0):
            raise LearningError("max_pairs_per_sequence must be null or a positive integer")
        if selection["metric"] != "validation_weighted_motion_loss" or selection["mode"] != "min":
            raise LearningError("V1 selection must minimize validation_weighted_motion_loss")
        return cls(
            model=ModelConfig(
                image_height_px=image["height_px"],  # type: ignore[arg-type]
                image_width_px=image["width_px"],  # type: ignore[arg-type]
                visual_feature_dim=model["visual_feature_dim"],  # type: ignore[arg-type]
                imu_hidden_dim=model["imu_hidden_dim"],  # type: ignore[arg-type]
                fusion_hidden_dim=model["fusion_hidden_dim"],  # type: ignore[arg-type]
                dropout_probability=model["dropout"],  # type: ignore[arg-type]
                rotation_state_source=model.get(
                    "rotation_state_source", "shared-recurrent-fusion-state/v1"
                ),  # type: ignore[arg-type]
            ),
            data=DataConfig(
                image_mean=image["mean"],  # type: ignore[arg-type]
                image_std=image["std"],  # type: ignore[arg-type]
                gyroscope_scale_rad_s=model["gyro_scale_rad_s"],  # type: ignore[arg-type]
                accelerometer_scale_m_s2=model["acceleration_scale_m_s2"],  # type: ignore[arg-type]
            ),
            batch_size=optimization["batch_size"],  # type: ignore[arg-type]
            epochs=optimization["epochs"],  # type: ignore[arg-type]
            learning_rate=optimization["learning_rate"],  # type: ignore[arg-type]
            weight_decay=optimization["weight_decay"],  # type: ignore[arg-type]
            translation_loss_weight=optimization["translation_loss_weight"],  # type: ignore[arg-type]
            rotation_loss_weight=optimization["rotation_loss_weight"],  # type: ignore[arg-type]
            gradient_clip_norm=optimization["gradient_clip_norm"],  # type: ignore[arg-type]
            num_workers=optimization["num_workers"],  # type: ignore[arg-type]
            seed=value["seed"],  # type: ignore[arg-type]
            use_amp=optimization["amp"],  # type: ignore[arg-type]
            deterministic=True,
        )


def _exact_mapping(
    value: object,
    fields: set[str],
    *,
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise LearningError(f"{field} must be a mapping with exact fields {sorted(fields)!r}")
    return value


__all__ = ["DataConfig", "ModelConfig", "TrainingConfig"]
