"""Optional local upload UI for recorded CompactVIO inference.

Gradio is imported only when :func:`build_demo` is called, so training,
evaluation, the CLI, and ``--help`` do not acquire a UI dependency.
"""

from __future__ import annotations

import argparse
import html
import shutil
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path

from compact_vio.learning.errors import LearningError

_WEB_UPLOAD_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
_MAX_RETAINED_RESULT_DIRECTORIES = 8


def _prune_completed_result_directories(root: Path) -> None:
    """Keep a bounded set of completed UI results without touching active runs."""

    completed: list[tuple[int, Path]] = []
    for path in root.iterdir():
        if path.is_symlink() or not path.is_dir() or not (path / "summary.json").is_file():
            continue
        try:
            modified_ns = path.stat().st_mtime_ns
        except OSError:
            continue
        completed.append((modified_ns, path))
    completed.sort(reverse=True)
    for _, stale in completed[_MAX_RETAINED_RESULT_DIRECTORIES - 1 :]:
        shutil.rmtree(stale, ignore_errors=True)


def _path(value: object, *, field: str, required: bool = True) -> str | None:
    if value is None or value == "":
        if required:
            raise LearningError(f"{field} is required")
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return value
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    raise LearningError(f"{field} upload has an unsupported value")


def _model_is_ready(value: object) -> bool:
    """Return whether the UI has a non-empty model artifact path."""

    return isinstance(value, str) and bool(value.strip())


def _model_setup_panel() -> str:
    return """
<section class="cvio-panel cvio-setup-required" role="status">
  <p class="cvio-eyebrow">Model package required</p>
  <h2>Add the checked model package before running inference</h2>
  <p>This checkout does not include model weights. Open <strong>Advanced model settings</strong>
  and enter the package <code>manifest.json</code> path. The run and upload controls unlock when a
  path is present.</p>
</section>
""".strip()


def _completion_status(
    *,
    pair_count: int,
    frame_count: int,
    path_length_m: float,
    quality_warning: object | None,
) -> str:
    status = (
        f"Run completed: {pair_count} motion estimates from {frame_count} frames; "
        f"estimated path {path_length_m:.3f} m."
    )
    if quality_warning:
        return f"{status} Model accuracy is not yet reliable."
    return status


def _idle_panel() -> str:
    return """
<section class="cvio-panel cvio-idle" aria-live="polite">
  <p class="cvio-eyebrow">Ready</p>
  <h2>Run the example or upload one recording bundle</h2>
  <p>The estimated 3D path, a plain-language quality note, and download files will appear here.</p>
</section>
""".strip()


def _error_panel(message: object) -> str:
    safe_message = html.escape(str(message))
    return f"""
<section class="cvio-panel cvio-error" role="alert" aria-live="assertive">
  <p class="cvio-eyebrow">Input needed</p>
  <h2>This recording could not be processed</h2>
  <p>{safe_message}</p>
  <p class="cvio-help">The easiest input is one CompactVIO bundle ZIP. Separate files are
  available under <strong>Advanced: use separate files</strong>.</p>
</section>
""".strip()


def _completion_panel(
    *,
    pair_count: int,
    frame_count: int,
    path_length_m: float,
    final_displacement_m: float,
    elapsed_s: float,
    quality: object,
) -> str:
    quality_status = str(getattr(quality, "status", "not_assessed"))
    quality_headline = html.escape(str(getattr(quality, "headline", "Accuracy not verified")))
    quality_explanation = html.escape(str(getattr(quality, "explanation", "")))
    recommended_use = html.escape(str(getattr(quality, "recommended_use", "")))
    failed_gates = getattr(quality, "failed_gates", ())
    quality_label = {
        "accepted": "Benchmark passed",
        "rejected": "Benchmark not passed",
    }.get(quality_status, "Benchmark not available")
    quality_class = {
        "accepted": "cvio-quality-pass",
        "rejected": "cvio-quality-limited",
    }.get(quality_status, "cvio-quality-unknown")
    failed_html = ""
    if type(failed_gates) in (list, tuple) and failed_gates:
        failures = ", ".join(html.escape(str(item)) for item in failed_gates)
        failed_html = f"<p><strong>Failed checks:</strong> {failures}.</p>"
    development_passed = getattr(quality, "development_passed", 0)
    development_total = getattr(quality, "development_total", 0)
    development_html = ""
    if type(development_passed) is int and type(development_total) is int and development_total:
        development_html = (
            f"<p>{development_passed}/{development_total} development recordings passed; "
            "the separate held-out test determines the overall verdict.</p>"
        )
    short_recording = ""
    if pair_count < 10:
        step_word = "step" if pair_count == 1 else "steps"
        short_recording = (
            '<p class="cvio-short-note"><strong>Very short recording:</strong> '
            f"this result contains only {pair_count} movement {step_word}. Upload a longer "
            "recording for a meaningful path shape.</p>"
        )
    estimate_word = "estimate" if pair_count == 1 else "estimates"
    return f"""
<section class="cvio-result" aria-live="polite">
  <div class="cvio-panel cvio-run-complete" role="status">
    <p class="cvio-eyebrow">Trajectory created</p>
    <h2>Your recording was processed successfully</h2>
    <p><strong>{frame_count} frames</strong> produced <strong>{pair_count} motion
    {estimate_word}</strong>. Scroll to the chart to inspect the estimated local path.</p>
  </div>
  <div class="cvio-metrics" aria-label="Estimated motion summary">
    <div><span>Estimated distance travelled</span><strong>{path_length_m:.3f} m</strong></div>
    <div><span>Start-to-end distance</span><strong>{final_displacement_m:.3f} m</strong></div>
    <div><span>Frames processed</span><strong>{frame_count}</strong></div>
    <div><span>Processing time</span><strong>{elapsed_s:.3f} s</strong></div>
  </div>
  {short_recording}
  <div class="cvio-panel cvio-quality {quality_class}">
    <p class="cvio-eyebrow">Accuracy for this recording: unverified</p>
    <h2>Use this as a rough motion estimate, not a measurement</h2>
    <p>This upload has no ground-truth path, so the app cannot tell whether its distance or
    position is correct. The files were processed successfully; accuracy is a separate question.</p>
    <p><strong>Packaged model:</strong> {quality_label}. {quality_headline}</p>
    <details>
      <summary>Why this warning is shown</summary>
      <p>{quality_explanation}</p>
      <p><strong>Appropriate use:</strong> {recommended_use}</p>
      {development_html}{failed_html}
    </details>
  </div>
</section>
""".strip()


def _result_archive(result: object) -> Path:
    """Bundle the four user-facing result files into one convenient download."""

    paths = (
        result.summary_html,
        result.summary_json,
        result.trajectory_csv,
        result.trajectory_svg,
    )
    output = Path(paths[0]).parent / "compact-vio-result.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path_value in paths:
            path = Path(path_value)
            archive.write(path, path.name)
    return output


_APP_CSS = """
.gradio-container {
  max-width: 1180px !important;
  margin: 0 auto !important;
  padding: 32px 24px 64px !important;
}
.cvio-hero {
  padding: 28px;
  border: 1px solid var(--border-color-primary);
  border-radius: 18px;
  background: linear-gradient(
    135deg,
    var(--background-fill-secondary),
    var(--block-background-fill)
  );
  margin-bottom: 20px;
}
.cvio-hero h1 { margin: 0 0 10px; font-size: clamp(1.9rem, 4vw, 3rem); line-height: 1.08; }
.cvio-hero p { max-width: 760px; font-size: 1.05rem; line-height: 1.6; margin: 0; }
.cvio-kicker {
  margin: 0 0 8px !important;
  color: #fb923c;
  font-size: .78rem !important;
  font-weight: 800;
  letter-spacing: .12em;
  text-transform: uppercase;
}
.cvio-model-note {
  display: inline-block;
  margin-top: 16px;
  padding: 7px 10px;
  border: 1px solid #f59e0b;
  border-radius: 999px;
  color: #fcd34d;
  font-size: .82rem;
  font-weight: 700;
}
.cvio-guide, .cvio-panel {
  padding: 18px 20px;
  border: 1px solid var(--border-color-primary);
  border-radius: 14px;
  background: var(--background-fill-secondary);
}
.cvio-guide { margin: 0 0 24px; }
.cvio-guide strong { display: block; margin-bottom: 4px; }
.cvio-action-copy {
  min-height: 112px;
  padding: 4px 2px 10px;
}
.cvio-action-copy h2 { margin: 0 0 6px; font-size: 1.3rem; }
.cvio-action-copy p { margin: 0; color: var(--body-text-color-subdued); line-height: 1.5; }
.cvio-workflow {
  margin: 24px 0;
  padding: 14px 18px;
  border-top: 1px solid var(--border-color-primary);
  border-bottom: 1px solid var(--border-color-primary);
  color: var(--body-text-color-subdued);
  text-align: center;
}
.cvio-workflow strong { color: var(--body-text-color); }
.cvio-section-title { margin: 28px 0 8px; }
.cvio-section-title h2 { margin-bottom: 4px; }
.cvio-section-title p { color: var(--body-text-color-subdued); margin-top: 0; }
.cvio-eyebrow {
  margin: 0 0 6px !important;
  text-transform: uppercase;
  letter-spacing: .1em;
  font-size: .76rem;
  font-weight: 800;
}
.cvio-panel h2 { margin: 0 0 8px; font-size: 1.35rem; }
.cvio-panel p { line-height: 1.55; }
.cvio-idle { margin-top: 28px; border-style: dashed; }
.cvio-run-complete {
  border-color: #22c55e;
  background: color-mix(in srgb, #14532d 38%, transparent);
}
.cvio-run-complete .cvio-eyebrow { color: #86efac; }
.cvio-error {
  margin-top: 28px;
  border-color: #ef4444;
  background: color-mix(in srgb, #7f1d1d 36%, transparent);
}
.cvio-error .cvio-eyebrow { color: #fca5a5; }
.cvio-setup-required {
  margin: 18px 0 8px;
  border-color: #60a5fa;
  background: color-mix(in srgb, #1e3a8a 28%, transparent);
}
.cvio-setup-required .cvio-eyebrow { color: #93c5fd; }
.cvio-help { color: var(--body-text-color-subdued); }
.cvio-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 14px 0;
}
.cvio-metrics > div {
  padding: 16px;
  border: 1px solid var(--border-color-primary);
  border-radius: 12px;
  background: var(--block-background-fill);
}
.cvio-metrics span {
  display: block;
  min-height: 2.5em;
  color: var(--body-text-color-subdued);
  font-size: .85rem;
}
.cvio-metrics strong { display: block; font-size: 1.25rem; margin-top: 5px; }
.cvio-short-note {
  padding: 12px 16px;
  border-left: 4px solid #60a5fa;
  background: color-mix(in srgb, #1e3a8a 24%, transparent);
}
.cvio-quality { margin-top: 14px; }
.cvio-quality-limited {
  border-color: #f59e0b;
  background: color-mix(in srgb, #78350f 38%, transparent);
}
.cvio-quality-limited .cvio-eyebrow { color: #fcd34d; }
.cvio-quality-pass { border-color: #22c55e; }
.cvio-quality-pass .cvio-eyebrow { color: #86efac; }
.cvio-quality-unknown .cvio-eyebrow { color: #93c5fd; }
.cvio-quality details { margin-top: 12px; }
.cvio-quality summary { cursor: pointer; font-weight: 700; }
#trajectory-panel { margin-top: 18px; }
#trajectory-panel svg { width: 100%; height: auto; border-radius: 14px; }
.cvio-download-heading { margin-top: 24px; }
@media (max-width: 760px) {
  .gradio-container { padding: 18px 12px 42px !important; }
  .cvio-hero { padding: 20px; }
  .cvio-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
"""


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

    from compact_vio.learning.demo_bundle import (
        create_workflow_example_bundle,
        open_recording_bundle,
    )
    from compact_vio.learning.recording_inference import (
        TorchCheckpointBackend,
        assess_model_quality,
        run_recording,
    )

    actual_device = device
    if device == "auto":
        try:
            import torch
        except ImportError as exc:
            raise LearningError("automatic demo device selection requires PyTorch") from exc
        actual_device = "cuda" if torch.cuda.is_available() else "cpu"

    if checkpoint_path is None and model_package_path is None:
        local_package = Path(
            "outputs/raft-hybrid-experimental-20260830/model-package/manifest.json"
        )
        if local_package.is_file():
            model_package_path = local_package

    default_model = (
        str(model_package_path)
        if model_package_path is not None
        else str(checkpoint_path)
        if checkpoint_path is not None
        else ""
    )
    default_kind = "Legacy checkpoint" if checkpoint_path is not None else "RAFT hybrid package"
    model_ready = _model_is_ready(default_model)
    result_workspace = tempfile.TemporaryDirectory(prefix="compact-vio-demo-results-")
    result_root = Path(result_workspace.name)

    def infer_paths(
        *,
        recording_path: str,
        camera_path: str | None,
        imu_path: str,
        calibration_path: str | None,
        sequence_id: str,
        model_kind: str,
        model_artifact: str,
        state_policy: str,
    ) -> tuple[object, object, object, object, object, object, object]:
        output: Path | None = None
        try:
            if not isinstance(model_artifact, str) or not model_artifact.strip():
                raise LearningError(
                    "No model package is configured. Add its manifest path under "
                    "Advanced model settings."
                )
            model_value = _path(model_artifact.strip(), field="model artifact")
            assert model_value is not None
            if Path(recording_path).suffix.lower() == ".mp4" and camera_path is None:
                raise LearningError("Add a camera-timestamps CSV for the MP4 recording.")
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
            _prune_completed_result_directories(result_root)
            output = Path(tempfile.mkdtemp(prefix="run-", dir=result_root))
            result = run_recording(
                recording_path=recording_path,
                camera_timestamps_path=camera_path,
                imu_csv_path=imu_path,
                calibration_path=calibration_path,
                output_directory=output,
                backend=backend,  # type: ignore[arg-type]
                sequence_id=sequence_id,
            )
            svg = result.trajectory_svg.read_text(encoding="utf-8")
            status = _completion_panel(
                pair_count=result.pair_count,
                frame_count=result.frame_count,
                path_length_m=result.path_length_m,
                final_displacement_m=result.final_displacement_m,
                elapsed_s=result.elapsed_s,
                quality=assess_model_quality(backend),
            )
            return (
                status,
                gr.update(value=svg, visible=True),
                gr.update(value=str(_result_archive(result)), visible=True),
                gr.update(value=str(result.summary_html), visible=True),
                gr.update(value=str(result.summary_json), visible=True),
                gr.update(value=str(result.trajectory_csv), visible=True),
                gr.update(value=str(result.trajectory_svg), visible=True),
            )
        except (LearningError, OSError, RuntimeError, ValueError) as exc:
            if output is not None:
                shutil.rmtree(output, ignore_errors=True)
            return (
                _error_panel(exc),
                gr.update(value="", visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
            )

    def infer_manual(
        recording: object,
        camera_timestamps: object,
        imu: object,
        calibration: object,
        model_kind: str,
        model_artifact: str,
        state_policy: str,
    ) -> tuple[object, object, object, object, object, object, object]:
        try:
            recording_path = _path(recording, field="recording")
            camera_path = _path(camera_timestamps, field="camera timestamps", required=False)
            imu_path = _path(imu, field="IMU")
            calibration_path = _path(calibration, field="calibration", required=False)
            assert recording_path is not None
            assert imu_path is not None
            return infer_paths(
                recording_path=recording_path,
                camera_path=camera_path,
                imu_path=imu_path,
                calibration_path=calibration_path,
                sequence_id=Path(recording_path).stem,
                model_kind=model_kind,
                model_artifact=model_artifact,
                state_policy=state_policy,
            )
        except (LearningError, OSError, RuntimeError, ValueError) as exc:
            return (
                _error_panel(exc),
                gr.update(value="", visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
            )

    def infer_bundle(
        bundle: object,
        model_kind: str,
        model_artifact: str,
        state_policy: str,
    ) -> tuple[object, object, object, object, object, object, object]:
        try:
            bundle_path = _path(bundle, field="recording bundle")
            assert bundle_path is not None
            with open_recording_bundle(bundle_path) as opened:
                return infer_paths(
                    recording_path=str(opened.recording_path),
                    camera_path=str(opened.camera_timestamps_path)
                    if opened.camera_timestamps_path is not None
                    else None,
                    imu_path=str(opened.imu_csv_path),
                    calibration_path=str(opened.calibration_path),
                    sequence_id=opened.display_name,
                    model_kind=model_kind,
                    model_artifact=model_artifact,
                    state_policy=state_policy,
                )
        except (LearningError, OSError, RuntimeError, ValueError) as exc:
            return (
                _error_panel(exc),
                gr.update(value="", visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
            )

    def infer_example(
        model_kind: str,
        model_artifact: str,
        state_policy: str,
    ) -> tuple[object, object, object, object, object, object, object]:
        try:
            with tempfile.TemporaryDirectory(prefix="compact-vio-example-run-") as directory:
                bundle_path = create_workflow_example_bundle(
                    Path(directory) / "example-recording.zip"
                )
                return infer_bundle(bundle_path, model_kind, model_artifact, state_policy)
        except (LearningError, OSError, RuntimeError, ValueError) as exc:
            return (
                _error_panel(exc),
                gr.update(value="", visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
                gr.update(value=None, visible=False),
            )

    with gr.Blocks(
        title="CompactVIO Trajectory Estimator",
        delete_cache=(3600, 86400),
    ) as demo:
        gr.HTML(
            """
<header class="cvio-hero">
  <p class="cvio-kicker">Compact hybrid visual-inertial odometry</p>
  <h1>Turn camera + IMU motion into a local 3D path</h1>
  <p>Start with the built-in example or upload one recording bundle. CompactVIO processes the
  recording locally and returns a trajectory chart, CSV, and readable report.</p>
  <span class="cvio-model-note">Research preview · quality is shown after each run</span>
</header>
""".strip()
        )
        gr.HTML(
            """
<div class="cvio-workflow" aria-label="CompactVIO workflow">
  <strong>Camera frames + IMU</strong> &rarr; optical and inertial motion &rarr;
  compact translation model &rarr; <strong>local 3D trajectory</strong>
</div>
""".strip()
        )
        model_setup = gr.HTML(value=_model_setup_panel(), visible=not model_ready)
        with gr.Row():
            with gr.Column(scale=1):
                gr.HTML(
                    """
<div class="cvio-action-copy">
  <h2>Try the workflow</h2>
  <p>Runs a small synthetic camera + IMU example. It proves the software path works, not that the
  model is accurate.</p>
</div>
""".strip()
                )
                run_example = gr.Button(
                    "Run built-in example",
                    size="lg",
                    interactive=model_ready,
                )
            with gr.Column(scale=2):
                gr.HTML(
                    """
<div class="cvio-action-copy">
  <h2>Use your recording</h2>
  <p>Choose one ZIP containing camera frames, timestamps, IMU readings, and calibration.
  Processing starts automatically.</p>
</div>
""".strip()
                )
                bundle = gr.File(
                    label="Recording bundle (.zip)",
                    type="filepath",
                    file_types=[".zip"],
                    interactive=model_ready,
                )

        with gr.Accordion("Advanced: use separate files", open=False):
            gr.Markdown(
                "Use this only when your camera, IMU, and calibration are not packaged together."
            )
            with gr.Row():
                recording = gr.File(
                    label="Camera recording (.mp4 or timestamped image .zip)",
                    type="filepath",
                    file_types=[".mp4", ".zip"],
                )
                camera_timestamps = gr.File(
                    label="Camera timestamps (required for MP4)",
                    type="filepath",
                    file_types=[".csv"],
                )
            with gr.Row():
                imu = gr.File(label="Synchronized IMU (.csv)", type="filepath", file_types=[".csv"])
                calibration = gr.File(
                    label="Camera + IMU calibration",
                    type="filepath",
                    file_types=[".json", ".yaml", ".yml"],
                )
            run_manual = gr.Button(
                "Analyze separate files",
                variant="primary",
                interactive=model_ready,
            )

        with gr.Accordion("Advanced model settings", open=False):
            gr.Markdown(
                "The local package is selected automatically when available. Most users should "
                "leave these settings unchanged."
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

        gr.HTML(
            """
<div class="cvio-section-title">
  <h2>Result</h2>
  <p>The chart is a raw local estimate. It is not GPS, a global map, or proof of accuracy.</p>
</div>
""".strip()
        )
        status = gr.HTML(value=_idle_panel(), elem_id="result-status")
        trajectory = gr.HTML(visible=False, elem_id="trajectory-panel")
        result_archive = gr.File(label="Download all results (.zip)", visible=False)
        with gr.Accordion("Individual result files", open=False):
            with gr.Row():
                report_output = gr.File(label="Readable report (.html)", visible=False)
                json_output = gr.File(label="Run summary (.json)", visible=False)
                csv_output = gr.File(label="Trajectory data (.csv)", visible=False)
                svg_output = gr.File(label="Trajectory image (.svg)", visible=False)

        model_kind.change(
            fn=lambda kind: gr.update(visible=kind == "Legacy checkpoint"),
            inputs=model_kind,
            outputs=state_policy,
        )
        model_artifact.input(
            fn=lambda artifact: (
                gr.update(visible=not _model_is_ready(artifact)),
                gr.update(interactive=_model_is_ready(artifact)),
                gr.update(interactive=_model_is_ready(artifact)),
                gr.update(interactive=_model_is_ready(artifact)),
            ),
            inputs=model_artifact,
            outputs=(model_setup, run_example, bundle, run_manual),
        )
        shared_outputs = (
            status,
            trajectory,
            result_archive,
            report_output,
            json_output,
            csv_output,
            svg_output,
        )
        run_example.click(
            fn=infer_example,
            inputs=(model_kind, model_artifact, state_policy),
            outputs=shared_outputs,
            scroll_to_output=True,
            show_progress="full",
            concurrency_limit=1,
        )
        bundle.upload(
            fn=infer_bundle,
            inputs=(bundle, model_kind, model_artifact, state_policy),
            outputs=shared_outputs,
            scroll_to_output=True,
            show_progress="full",
            concurrency_limit=1,
        )
        run_manual.click(
            fn=infer_manual,
            inputs=(
                recording,
                camera_timestamps,
                imu,
                calibration,
                model_kind,
                model_artifact,
                state_policy,
            ),
            outputs=shared_outputs,
            scroll_to_output=True,
            show_progress="full",
            concurrency_limit=1,
        )
    demo._compact_vio_result_workspace = result_workspace  # type: ignore[attr-defined]
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
    parser.add_argument(
        "--host",
        choices=("127.0.0.1", "localhost", "::1"),
        default="127.0.0.1",
        help="loopback interface; the upload demo is intentionally local-only",
    )
    parser.add_argument("--port", type=int, default=7860)
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
        demo.launch(  # type: ignore[attr-defined]
            server_name=args.host,
            server_port=args.port,
            share=False,
            css=_APP_CSS,
            max_file_size=_WEB_UPLOAD_LIMIT_BYTES,
        )
    except (LearningError, OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"compact-vio-demo: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "_completion_panel",
    "_completion_status",
    "_error_panel",
    "_idle_panel",
    "build_demo",
    "build_parser",
    "main",
]
