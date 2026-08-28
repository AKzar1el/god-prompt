from pathlib import Path

import pytest

pytest.importorskip('inspect_ai')

from godprompt_bench.eval import build_task

ROOT = Path(__file__).parents[1]
REPO_ROOT = ROOT.parent


def test_current_inspect_api_builds_both_conditions():
    for condition in ('baseline', 'godprompt'):
        task = build_task(
            condition,
            ROOT,
            REPO_ROOT,
            ['impl-py-slugify'],
            epochs=1,
            max_messages=5,
            max_time_seconds=30,
            max_output_tokens=1024,
        )
        assert task is not None
