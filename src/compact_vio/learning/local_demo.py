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


def build_demo(
    *,
    checkpoint_path: Path | str | None = None,
    device: str = "cpu",
) -> object:
    """Build the local Gradio app without launching it."""

    try:
        import gradio as gr  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LearningError("the local upload demo requires the optional Gradio extra") from exc

    from compact_vio.learning.recording_inference import (
        TorchCheckpointBackend,
        run_recording,
    )

    default_checkpoint = str(checkpoint_path) if checkpoint_path is not None else ""

    def infer(
        recording: object,
        camera_timestamps: object,
        imu: object,
        calibration: object,
        checkpoint: str,
        state_policy: str,
    ) -> tuple[str, str, str, str, str]:
        try:
            recording_path = _path(recording, field="recording")
            camera_path = _path(camera_timestamps, field="camera timestamps", required=False)
            imu_path = _path(imu, field="IMU")
            calibration_path = _path(calibration, field="calibration", required=False)
            checkpoint_value = _path(checkpoint.strip(), field="checkpoint")
            assert recording_path is not None
            assert imu_path is not None
            assert checkpoint_value is not None
            output = Path(tempfile.mkdtemp(prefix="compact-vio-demo-result-"))
            backend = TorchCheckpointBackend(
                checkpoint_value,
                device=device,
                state_policy=state_policy,
            )
            result = run_recording(
                recording_path=recording_path,
                camera_timestamps_path=camera_path,
                imu_csv_path=imu_path,
                calibration_path=calibration_path,
                output_directory=output,
                backend=backend,
                sequence_id=Path(recording_path).stem,
            )
            svg = result.trajectory_svg.read_text(encoding="utf-8")
            status = (
                f"Completed {result.pair_count} motion pairs from {result.frame_count} frames; "
                f"predicted path length {result.path_length_m:.3f} m."
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
            calibration = gr.File(label="Calibration JSON/YAML", type="filepath")
        checkpoint = gr.Textbox(label="Checkpoint path", value=default_checkpoint)
        state_policy = gr.Radio(
            choices=("stateful", "independent"),
            value="stateful",
            label="Inference state policy",
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
            inputs=(recording, camera_timestamps, imu, calibration, checkpoint, state_policy),
            outputs=(status, trajectory, csv_output, svg_output, report_output),
        )
    return demo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-demo",
        description="Launch the local CompactVIO recording upload demo.",
    )
    parser.add_argument("--checkpoint", help="default checkpoint path shown in the demo")
    parser.add_argument("--device", default="cpu", help="PyTorch device, for example cpu or cuda")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--share", action="store_true", help="ask Gradio to create a share link")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        demo = build_demo(checkpoint_path=args.checkpoint, device=args.device)
        demo.launch(server_name=args.host, server_port=args.port, share=args.share)  # type: ignore[attr-defined]
    except (LearningError, OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"compact-vio-demo: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_demo", "build_parser", "main"]
