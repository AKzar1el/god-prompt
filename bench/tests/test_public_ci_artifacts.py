from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_FILES = {"manifest.json", "summary.json", "scores.csv", "trajectories.jsonl"}


def test_benchmark_workflows_upload_only_curated_public_outputs():
    for workflow, roots in (
        ("bench-run.yml", ("bench/results",)),
        ("bench-half-spike.yml", ("bench/results-simulated-half", "bench/results-real-smoke")),
    ):
        source = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        artifact_step = source.split("uses: actions/upload-artifact@v7", 1)[1]
        paths = artifact_step.split("path: |", 1)[1].split("if-no-files-found:", 1)[0]
        published = {line.strip() for line in paths.splitlines() if line.strip()}
        expected = {f"{root}/*/{name}" for root in roots for name in PUBLIC_FILES}
        assert published == expected, f"{workflow} must not publish raw Inspect logs or directories"
