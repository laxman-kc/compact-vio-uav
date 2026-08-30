"""Optional local upload UI for recorded CompactVIO inference.

Gradio is imported only when :func:`build_demo` is called, so training,
evaluation, the CLI, and ``--help`` do not acquire a UI dependency.
"""

from __future__ import annotations

import argparse
import html
import tempfile
from collections.abc import Sequence
from pathlib import Path

from compact_vio.learning.errors import LearningError


def _path(value: object, *, field: str, required: bool = True) -> str | None:
    if value is None or value == "":
        if required:
            raise LearningError(f"{field} is required")
        return None
    if isinstance(value, str):
        return value
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    raise LearningError(f"{field} upload has an unsupported value")


def _completion_status(
    *,
    pair_count: int,
    frame_count: int,
    path_length_m: float,
    quality_warning: object | None,
) -> str:
    status = (
        f"Completed {pair_count} motion pairs from {frame_count} frames; "
        f"predicted path length {path_length_m:.3f} m."
    )
    if quality_warning:
        return f"⚠️ **MODEL QUALITY WARNING:** {quality_warning}\n\n{status}"
    return status


def build_demo(
    *,
    checkpoint_path: Path | str | None = None,
    model_package_path: Path | str | None = None,
    device: str = "auto",
) -> object:
    """Build the local Gradio app without launching it."""

    if checkpoint_path is not None and model_package_path is not None:
        raise LearningError("provide either checkpoint_path or model_package_path, not both")

    try:
        import gradio as gr  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LearningError("the local upload demo requires the optional Gradio extra") from exc

    from compact_vio.learning.recording_inference import (
        TorchCheckpointBackend,
        run_recording,
    )

    actual_device = device
    if device == "auto":
        try:
            import torch
        except ImportError as exc:
            raise LearningError("automatic demo device selection requires PyTorch") from exc
        actual_device = "cuda" if torch.cuda.is_available() else "cpu"

    default_model = (
        str(model_package_path)
        if model_package_path is not None
        else str(checkpoint_path)
        if checkpoint_path is not None
        else ""
    )
    default_kind = "RAFT hybrid package" if model_package_path is not None else "Legacy checkpoint"

    def infer(
        recording: object,
        camera_timestamps: object,
        imu: object,
        calibration: object,
        model_kind: str,
        model_artifact: str,
        state_policy: str,
    ) -> tuple[str, str, str, str, str]:
        try:
            recording_path = _path(recording, field="recording")
            camera_path = _path(camera_timestamps, field="camera timestamps", required=False)
            imu_path = _path(imu, field="IMU")
            calibration_path = _path(calibration, field="calibration", required=False)
            model_value = _path(model_artifact.strip(), field="model artifact")
            assert recording_path is not None
            assert imu_path is not None
            assert model_value is not None
            output = Path(tempfile.mkdtemp(prefix="compact-vio-demo-result-"))
            if model_kind == "RAFT hybrid package":
                if calibration_path is None:
                    raise LearningError("calibration is required for a RAFT hybrid package")
                from compact_vio.learning.raft_hybrid import RaftHybridBackend

                backend: object = RaftHybridBackend(model_value, device=actual_device)
            elif model_kind == "Legacy checkpoint":
                backend = TorchCheckpointBackend(
                    model_value,
                    device=actual_device,
                    state_policy=state_policy,
                )
            else:
                raise LearningError("unsupported model kind")
            result = run_recording(
                recording_path=recording_path,
                camera_timestamps_path=camera_path,
                imu_csv_path=imu_path,
                calibration_path=calibration_path,
                output_directory=output,
                backend=backend,  # type: ignore[arg-type]
                sequence_id=Path(recording_path).stem,
            )
            svg = result.trajectory_svg.read_text(encoding="utf-8")
            status = _completion_status(
                pair_count=result.pair_count,
                frame_count=result.frame_count,
                path_length_m=result.path_length_m,
                quality_warning=getattr(backend, "quality_warning", None),
            )
            return (
                status,
                svg,
                str(result.trajectory_csv),
                str(result.trajectory_svg),
                str(result.summary_html),
            )
        except (LearningError, OSError, RuntimeError, ValueError) as exc:
            return (
                f"Inference failed: {html.escape(str(exc))}",
                "",
                "",
                "",
                "",
            )

    with gr.Blocks(title="CompactVIO Recording Demo") as demo:
        gr.Markdown(
            "# CompactVIO recording demo\n"
            "Upload an MP4 (plus camera timestamps) or a ZIP of timestamped images, "
            "the synchronized IMU CSV, and calibration. Run the model and download the trajectory."
        )
        with gr.Row():
            recording = gr.File(label="Recording (.mp4 or image .zip)", type="filepath")
            camera_timestamps = gr.File(
                label="Camera timestamps CSV (required for MP4)", type="filepath"
            )
        with gr.Row():
            imu = gr.File(label="IMU CSV", type="filepath")
            calibration = gr.File(
                label="Combined camera/IMU calibration JSON/YAML",
                type="filepath",
            )
        model_kind = gr.Radio(
            choices=("RAFT hybrid package", "Legacy checkpoint"),
            value=default_kind,
            label="Model type",
        )
        model_artifact = gr.Textbox(
            label="Model package manifest or checkpoint path",
            value=default_model,
        )
        state_policy = gr.Radio(
            choices=("stateful", "independent"),
            value="stateful",
            label="Inference state policy",
            visible=default_kind == "Legacy checkpoint",
        )
        model_kind.change(
            fn=lambda kind: gr.update(visible=kind == "Legacy checkpoint"),
            inputs=model_kind,
            outputs=state_policy,
        )
        run = gr.Button("Run VIO", variant="primary")
        status = gr.Markdown()
        trajectory = gr.HTML()
        with gr.Row():
            csv_output = gr.File(label="Trajectory CSV")
            svg_output = gr.File(label="Trajectory SVG")
            report_output = gr.File(label="Self-contained HTML summary")
        run.click(
            fn=infer,
            inputs=(
                recording,
                camera_timestamps,
                imu,
                calibration,
                model_kind,
                model_artifact,
                state_policy,
            ),
            outputs=(status, trajectory, csv_output, svg_output, report_output),
        )
    return demo


def build_parser() -> argparse.ArgumentParser:
    from compact_vio.learning.recording_inference import _RAFT_CALIBRATION_EXAMPLE

    parser = argparse.ArgumentParser(
        prog="compact-vio-demo",
        description="Launch the local CompactVIO recording upload demo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_RAFT_CALIBRATION_EXAMPLE,
    )
    parser.add_argument("--checkpoint", help="default checkpoint path shown in the demo")
    parser.add_argument(
        "--model-package", help="default RAFT hybrid package manifest shown in the demo"
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="PyTorch device; default auto selects CUDA when available, otherwise CPU",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true", help="ask Gradio to create a share link")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.checkpoint is not None and args.model_package is not None:
            raise LearningError("--checkpoint and --model-package are mutually exclusive")
        demo = build_demo(
            checkpoint_path=args.checkpoint,
            model_package_path=args.model_package,
            device=args.device,
        )
        demo.launch(server_name=args.host, server_port=args.port, share=args.share)  # type: ignore[attr-defined]
    except (LearningError, OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"compact-vio-demo: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["_completion_status", "build_demo", "build_parser", "main"]
