#!/usr/bin/env python
"""
Guard against Python-version drift between config files.

pyproject.toml is the single source of truth for supported Python
versions: `requires-python` defines the floor, and the trove
classifiers enumerate every supported minor version. tox.ini and
.github/workflows/ci.yml cannot read that metadata natively, so these
tests assert they stay in sync. If you add or drop a Python version,
update pyproject.toml first; these tests point at every mirror that
must follow.
"""

import configparser
import re
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

CLASSIFIER_RE = re.compile(r"^Programming Language :: Python :: (3\.\d+)$")
TOX_ENV_RE = re.compile(r"^py(3)(\d+)$")


def pyproject():
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def classifier_versions():
    """Supported minor versions enumerated in pyproject classifiers."""
    return {
        m.group(1)
        for c in pyproject()["project"]["classifiers"]
        if (m := CLASSIFIER_RE.match(c))
    }


def tox_versions():
    """Minor versions in tox envlist (pyXYZ envs only)."""
    config = configparser.ConfigParser()
    config.read(REPO_ROOT / "tox.ini")
    envs = re.split(r"[,\s]+", config["tox"]["envlist"].strip())
    return {
        f"{m.group(1)}.{m.group(2)}"
        for env in envs
        if (m := TOX_ENV_RE.match(env))
    }


def ci_python_versions():
    """All python-version values in ci.yml: (matrix set, single-job set)."""
    with open(REPO_ROOT / ".github" / "workflows" / "ci.yml") as f:
        workflow = yaml.safe_load(f)
    matrix, singles = set(), set()
    for job in workflow["jobs"].values():
        matrix.update(
            job.get("strategy", {}).get("matrix", {}).get("python-version", [])
        )
        for step in job.get("steps", []):
            version = step.get("with", {}).get("python-version", "")
            if version and "${{" not in version:
                singles.add(version)
    return matrix, singles


class TestPythonVersionSync:
    """pyproject.toml classifiers are the source of truth (see module docstring)."""

    def test_requires_python_floor_matches_classifiers(self):
        requires = pyproject()["project"]["requires-python"]
        m = re.match(r">=\s*(3\.\d+)$", requires)
        assert m, f"Unexpected requires-python format: {requires!r}"
        floor = m.group(1)
        oldest = min(classifier_versions(), key=lambda v: tuple(map(int, v.split("."))))
        assert floor == oldest, (
            f"requires-python floor {floor} != oldest classifier {oldest}"
        )

    def test_tox_envlist_matches_classifiers(self):
        assert tox_versions() == classifier_versions(), (
            "tox.ini envlist out of sync with pyproject.toml classifiers"
        )

    def test_ci_matrix_matches_classifiers(self):
        matrix, _ = ci_python_versions()
        assert matrix == classifier_versions(), (
            "ci.yml test matrix out of sync with pyproject.toml classifiers"
        )

    def test_ci_single_version_jobs_use_supported_version(self):
        _, singles = ci_python_versions()
        assert singles, "Expected pinned python-version in lint/typecheck jobs"
        unsupported = singles - classifier_versions()
        assert not unsupported, (
            f"ci.yml jobs pin Python versions not in classifiers: {unsupported}"
        )
