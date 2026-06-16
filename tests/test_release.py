"""Tests verifying the PyPI release setup is correct.

Phase 16 introduced the first PyPI release for kb-tools. This module
guards the release scaffolding (pyproject metadata, release workflow,
install-smoke job, CHANGELOG, MANIFEST.in, README install section)
and exercises the wheel build + fresh-venv install end-to-end.

Network-bound tests (real PyPI publish) are intentionally out of scope.
"""

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
RELEASE_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"
TESTS_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "tests.yml"
CHANGELOG_PATH = REPO_ROOT / "CHANGELOG.md"
MANIFEST_IN_PATH = REPO_ROOT / "MANIFEST.in"
README_PATH = REPO_ROOT / "README.md"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pyproject_data() -> dict:
    """Parsed pyproject.toml as a dict."""
    with PYPROJECT_PATH.open("rb") as f:
        return tomllib.load(f)


@pytest.fixture(scope="module")
def release_workflow() -> dict:
    """Parsed .github/workflows/release.yml as a dict."""
    with RELEASE_WORKFLOW_PATH.open() as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def tests_workflow() -> dict:
    """Parsed .github/workflows/tests.yml as a dict."""
    with TESTS_WORKFLOW_PATH.open() as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def pyproject_version(pyproject_data: dict) -> str:
    return pyproject_data["project"]["version"]


# ---------------------------------------------------------------------------
# pyproject.toml — required PyPI fields
# ---------------------------------------------------------------------------


class TestPyprojectFields:
    """The pyproject.toml must declare every field PyPI displays."""

    def test_pyproject_has_required_pypi_fields(self, pyproject_data: dict):
        project = pyproject_data["project"]
        # Description, readme, requires-python, license, authors, keywords,
        # classifiers, urls are all required by Phase 16 design §B.
        for key in (
            "name",
            "version",
            "description",
            "readme",
            "requires-python",
            "license",
            "authors",
            "keywords",
            "classifiers",
        ):
            assert key in project, f"missing project field: {key}"
            value = project[key]
            assert value, f"project.{key} is empty"
        # urls is a top-level [project.urls] table
        assert "urls" in project, "missing [project.urls] table"
        assert project["urls"], "[project.urls] is empty"

    def test_pyproject_version_is_string(self, pyproject_data: dict):
        # PEP 621: version MUST be a string.
        version = pyproject_data["project"]["version"]
        assert isinstance(version, str), f"version is {type(version).__name__}, expected str"
        # Semantic-version-ish: digits separated by dots.
        assert re.match(r"^\d+\.\d+\.\d+", version), f"unexpected version: {version!r}"

    def test_pyproject_classifiers_include_python_versions(self, pyproject_data: dict):
        classifiers = pyproject_data["project"]["classifiers"]
        # Must advertise Python 3.11 / 3.12 / 3.13 per Phase 16 design §B.
        for minor in ("3.11", "3.12", "3.13"):
            assert any(minor in c for c in classifiers), (
                f"classifiers missing Python {minor}: {classifiers}"
            )

    def test_pyproject_classifiers_include_license(self, pyproject_data: dict):
        classifiers = pyproject_data["project"]["classifiers"]
        # Must declare the MIT license classifier.
        assert any("MIT License" in c for c in classifiers), (
            f"classifiers missing MIT License: {classifiers}"
        )

    def test_pyproject_has_project_urls(self, pyproject_data: dict):
        urls = pyproject_data["project"].get("urls", {})
        # Repository is the minimum useful URL on the PyPI sidebar.
        assert urls, "[project.urls] is empty"
        assert any("Repository" in k for k in urls), f"Repository URL missing: {urls}"
        # All URL values should be non-empty strings.
        for key, value in urls.items():
            assert value, f"[project.urls].{key} is empty"


# ---------------------------------------------------------------------------
# Release workflow
# ---------------------------------------------------------------------------


class TestReleaseWorkflow:
    """The release workflow must use Trusted Publishing (no API tokens)."""

    def test_release_workflow_exists(self):
        assert RELEASE_WORKFLOW_PATH.is_file(), (
            f"missing {RELEASE_WORKFLOW_PATH}"
        )

    def test_release_workflow_is_valid_yaml(self, release_workflow: dict):
        assert isinstance(release_workflow, dict)
        assert release_workflow, "release.yml parsed to empty dict"

    def test_release_workflow_uses_trusted_publishing(self, release_workflow: dict):
        # Read raw text once for the negative assertion.
        text = RELEASE_WORKFLOW_PATH.read_text()
        # Positive: id-token permission is required for Trusted Publishing.
        assert "id-token: write" in text, (
            "release.yml missing `id-token: write` (Trusted Publishing)"
        )
        # Positive: uses the official PyPA Trusted Publishing action.
        assert "pypa/gh-action-pypi-publish@release/v1" in text, (
            "release.yml missing pypa/gh-action-pypi-publish@release/v1"
        )
        # Negative: must NOT reference an API token.
        assert "PYPI_API_TOKEN" not in text, (
            "release.yml must not reference PYPI_API_TOKEN "
            "(Trusted Publishing only)"
        )

    def test_release_workflow_triggers_on_tag_push(self, release_workflow: dict):
        # PyYAML normalizes the YAML 1.1 boolean `on` to Python `True`.
        triggers = release_workflow.get(True) or release_workflow.get("on")
        assert triggers, "release.yml missing `on:` triggers"
        assert "push" in triggers, "release.yml must trigger on push"
        push = triggers["push"]
        assert "tags" in push, "release.yml push must scope to tags"
        tags = push["tags"]
        # YAML can parse this as a list or a single string; both are valid.
        if isinstance(tags, str):
            tag_list = [tags]
        else:
            tag_list = list(tags)
        # GitHub Actions uses shell-glob `*` (not regex). The tag
        # pattern in release.yml is literally `v*.*.*`, so the
        # glob must contain `v` and a dot-separated wildcard.
        for t in tag_list:
            assert t.startswith("v"), (
                f"tag glob must start with 'v': {t!r}"
            )
            assert "*" in t, (
                f"tag glob must contain '*' wildcard: {t!r}"
            )

    def test_release_workflow_has_pypi_environment(self, release_workflow: dict):
        jobs = release_workflow.get("jobs", {})
        # The publish job must pin an environment so the GitHub
        # Environment's required reviewers / secrets scoping applies.
        publish = jobs.get("publish")
        assert publish is not None, "release.yml missing publish job"
        env = publish.get("environment")
        assert env, "release.yml publish job missing `environment:`"
        # YAML can model the env as a string or {name: ...} dict.
        env_name = env if isinstance(env, str) else env.get("name")
        assert env_name, f"publish.environment.name is empty: {env!r}"


# ---------------------------------------------------------------------------
# tests.yml — install-smoke job
# ---------------------------------------------------------------------------


class TestInstallSmokeJob:
    """The install-smoke job must build the wheel and exercise the entry point."""

    def test_install_smoke_job_in_tests_yml(self, tests_workflow: dict):
        jobs = tests_workflow.get("jobs", {})
        assert "install-smoke" in jobs, "tests.yml missing install-smoke job"
        job = jobs["install-smoke"]
        # It should run after `test` to keep CI fast on a broken test suite.
        needs = job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        assert "test" in needs, (
            f"install-smoke must depend on `test` (got needs={needs!r})"
        )

    def test_install_smoke_builds_and_installs_wheel(self):
        text = TESTS_WORKFLOW_PATH.read_text()
        assert "python -m build --wheel" in text, (
            "install-smoke job missing `python -m build --wheel`"
        )
        assert "pip install dist/*.whl" in text, (
            "install-smoke job missing wheel install step"
        )
        # It must exercise the installed entry point.
        assert "kb --version" in text, (
            "install-smoke job missing `kb --version` smoke check"
        )


# ---------------------------------------------------------------------------
# README, CHANGELOG, MANIFEST.in
# ---------------------------------------------------------------------------


class TestDocsAndManifest:
    """User-facing release docs must lead with the right install command."""

    def test_changelog_exists(self):
        assert CHANGELOG_PATH.is_file(), f"missing {CHANGELOG_PATH}"

    def test_changelog_mentions_current_version(self, pyproject_version: str):
        text = CHANGELOG_PATH.read_text()
        assert f"[{pyproject_version}]" in text, (
            f"CHANGELOG.md does not mention current version {pyproject_version}"
        )

    def test_readme_install_section_starts_with_pip_install(self):
        # Read the first ~80 lines; the install section is near the top.
        text = "\n".join(README_PATH.read_text().splitlines()[:80])
        # Find the `pip install kb-tools` line and ensure it appears
        # *before* any `pip install -e` (editable / dev install) line.
        m_pypi = re.search(r"^\s*pip install kb-tools\s*$", text, re.MULTILINE)
        m_dev = re.search(r"^\s*pip install -e", text, re.MULTILINE)
        assert m_pypi, "README install section missing `pip install kb-tools`"
        if m_dev:
            assert m_pypi.start() < m_dev.start(), (
                "`pip install kb-tools` must come before `pip install -e` in README"
            )

    def test_manifest_in_includes_readme_and_prompts(self):
        assert MANIFEST_IN_PATH.is_file(), f"missing {MANIFEST_IN_PATH}"
        text = MANIFEST_IN_PATH.read_text()
        # README.md must be bundled with the sdist.
        assert "README.md" in text, "MANIFEST.in missing README.md"
        # The prompt files are non-Python package data; they must be
        # explicitly pulled in (otherwise they vanish from the sdist).
        assert "prompts" in text and "*.md" in text, (
            "MANIFEST.in must include prompt .md files"
        )


# ---------------------------------------------------------------------------
# Local wheel build (no PyPI)
# ---------------------------------------------------------------------------


class TestLocalBuild:
    """`python -m build` must produce a usable wheel locally."""

    def test_build_wheel_succeeds_locally(self, tmp_path: Path, pyproject_version: str):
        wheels_dir = tmp_path / "wheels"
        wheels_dir.mkdir()
        # The `build` package may not be in the dev venv; install it.
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "build"],
            check=True,
            timeout=180,
        )
        result = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(wheels_dir)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, (
            f"`python -m build --wheel` failed:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
        wheels = sorted(wheels_dir.glob("*.whl"))
        assert wheels, f"no .whl produced in {wheels_dir}"
        # The wheel filename embeds the version. Sanity-check it.
        expected = f"kb_tools-{pyproject_version}-"
        assert any(expected in w.name for w in wheels), (
            f"wheel name missing {expected!r}: {[w.name for w in wheels]}"
        )


# ---------------------------------------------------------------------------
# Fresh-venv install + entry point smoke
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestFreshVenvInstall:
    """Install the built wheel into a fresh venv and exercise `kb`."""

    @pytest.fixture(scope="class")
    def wheel_and_venv(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        """Build a wheel once, then install it into a brand-new venv.

        Returns the venv root. Building + installing once per class
        keeps the slow tests fast enough to run in CI.
        """
        work = tmp_path_factory.mktemp("kb-release-")
        wheels_dir = work / "wheels"
        wheels_dir.mkdir()
        venv_dir = work / "venv"

        # 1) Build the wheel.
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "build"],
            check=True,
            timeout=180,
        )
        build = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(wheels_dir)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert build.returncode == 0, build.stderr

        wheels = sorted(wheels_dir.glob("*.whl"))
        assert wheels, "no wheel built"
        wheel = wheels[0]

        # 2) Create a fresh venv. Skip on Windows; we only need POSIX here.
        if os.name != "posix":
            pytest.skip("fresh-venv install is POSIX-only")
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            timeout=60,
        )
        venv_python = venv_dir / "bin" / "python"
        venv_pip = venv_dir / "bin" / "pip"
        assert venv_python.is_file(), f"venv python missing: {venv_python}"

        # 3) Install the wheel into the venv. --no-deps keeps the test
        # offline-safe for the slow path; we still need click + pyyaml
        # for `kb --version` to work, so install them too.
        subprocess.run(
            [str(venv_pip), "install", "--quiet", "--upgrade", "pip"],
            check=True,
            timeout=120,
        )
        subprocess.run(
            [str(venv_pip), "install", "--quiet", str(wheel)],
            check=True,
            timeout=180,
        )
        # `kb` depends on click, flask, pypdf, pyyaml at runtime.
        subprocess.run(
            [
                str(venv_pip),
                "install",
                "--quiet",
                "click",
                "flask",
                "pypdf",
                "pyyaml",
            ],
            check=True,
            timeout=180,
        )
        return venv_dir

    def test_kb_entry_point_reports_version(
        self,
        wheel_and_venv: Path,
        pyproject_version: str,
    ):
        kb = wheel_and_venv / "bin" / "kb"
        assert kb.is_file(), f"entry point missing: {kb}"
        result = subprocess.run(
            [str(kb), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"`kb --version` failed:\nstdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        # Click's @version_option prints the version; allow loose matching
        # so future tweaks (e.g. `kb 0.2.0`) don't break the test.
        assert pyproject_version in result.stdout, (
            f"`kb --version` did not mention {pyproject_version}: "
            f"{result.stdout!r}"
        )

    def test_kb_help_works_after_wheel_install(self, wheel_and_venv: Path):
        kb = wheel_and_venv / "bin" / "kb"
        result = subprocess.run(
            [str(kb), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        # Click's Group --help lists the subcommands somewhere in the body.
        assert "Commands:" in result.stdout, (
            f"`kb --help` missing Commands: section:\n{result.stdout}"
        )

    def test_kb_init_add_search_after_wheel_install(self, wheel_and_venv: Path, tmp_path: Path):
        """End-to-end: init a bucket, add a doc, search it."""
        kb = wheel_and_venv / "bin" / "kb"
        bucket = tmp_path / "smoke-bucket"

        # `kb init <dir>`
        init = subprocess.run(
            [str(kb), "init", str(bucket)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert init.returncode == 0, (
            f"`kb init` failed:\nstdout: {init.stdout}\nstderr: {init.stderr}"
        )
        assert (bucket / "config" / "kb.yml").is_file(), (
            f"kb init did not create config/kb.yml in {bucket}"
        )

        # `kb add --title ... --content ...` inside the bucket.
        # `kb add` auto-indexes, so a follow-up `kb search` works.
        add = subprocess.run(
            [
                str(kb),
                "add",
                "--title",
                "smoke",
                "--content",
                "hello kb release smoke test",
            ],
            cwd=str(bucket),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert add.returncode == 0, (
            f"`kb add` failed:\nstdout: {add.stdout}\nstderr: {add.stderr}"
        )

        # `kb search` auto-detects the bucket from the cwd.
        # Use `--limit 1` to keep this fast.
        search = subprocess.run(
            [str(kb), "search", "hello", "--limit", "1"],
            cwd=str(bucket),
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert search.returncode == 0, (
            f"`kb search` failed:\nstdout: {search.stdout}\nstderr: {search.stderr}"
        )


# ---------------------------------------------------------------------------
# Repository hygiene — no stale build artifacts tracked by git
# ---------------------------------------------------------------------------


class TestRepoHygiene:
    """No egg-info, build, or dist directories should be git-tracked."""

    def test_no_egg_info_tracked(self):
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        tracked = result.stdout.splitlines()
        offenders = [p for p in tracked if "egg-info" in p]
        assert not offenders, f"egg-info paths are git-tracked: {offenders}"

    def test_no_build_dir_tracked(self):
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        tracked = result.stdout.splitlines()
        # `build/` and `dist/` are the two top-level dirs `python -m build`
        # creates. Neither should ever be committed.
        offenders = [
            p for p in tracked
            if p == "build" or p.startswith("build/")
            or p == "dist" or p.startswith("dist/")
        ]
        assert not offenders, (
            f"build/dist paths are git-tracked: {offenders}"
        )
