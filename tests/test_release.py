"""Tests verifying the wheel builds and installs cleanly in a fresh venv.

Per GOVERNANCE.md kb-tools is private (no PyPI publish, no public
release workflow). What remains useful from the Phase 16 work:

- The wheel still builds (python -m build --wheel exits 0)
- The wheel installs in a fresh venv (pip install dist/*.whl)
- The installed 'kb' entry point works end-to-end
  (kb --version, kb --help, kb init, kb add, kb search)
- The repo has no packaging artifacts tracked (egg-info, build/,
  dist/, MANIFEST, .venv/)

Network-bound tests (real PyPI publish) are intentionally out of
scope and were deleted alongside release.yml.
"""

import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
README_PATH = REPO_ROOT / "README.md"
GITIGNORE_PATH = REPO_ROOT / ".gitignore"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pyproject_data() -> dict:
    """Cached parse of pyproject.toml (slow to load, used by many tests)."""
    import tomllib

    with open(PYPROJECT_PATH, "rb") as f:
        return tomllib.load(f)


@pytest.fixture(scope="session")
def pyproject_version(pyproject_data: dict) -> str:
    return pyproject_data["project"]["version"]


@pytest.fixture(scope="session")
def built_wheel(tmp_path_factory: pytest.TempPathFactory, pyproject_version: str) -> Path:
    """Build the wheel once per test session, return path to the .whl file."""
    out = tmp_path_factory.mktemp("wheel")
    # Use the system pip (the one running the tests) so we don't fight
    # venvs in the middle of pytest.
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"python -m build failed:\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    wheels = list(out.glob("*.whl"))
    assert wheels, f"no wheel produced; build output:\n{result.stdout}"
    return wheels[0]


@pytest.fixture(scope="session")
def wheel_and_venv(
    built_wheel: Path, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """Build a fresh venv and install the wheel; return the venv path.

    Used by TestFreshVenvInstall to assert kb --version / --help / init
    work after a real wheel install in a clean environment.
    """
    venv = tmp_path_factory.mktemp("venv") / "kb-venv"
    t0 = time.time()
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv)],
        check=True,
        capture_output=True,
    )
    pip = venv / "bin" / "pip"
    subprocess.run(
        [str(pip), "install", "--quiet", "--upgrade", "pip"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [str(pip), "install", "--quiet", str(built_wheel)],
        check=True,
        capture_output=True,
        timeout=180,
    )
    print(f"\n[install-smoke] built + installed wheel in {time.time() - t0:.1f}s")
    return venv


# ---------------------------------------------------------------------------
# pyproject.toml — minimal but correct for a private package
# ---------------------------------------------------------------------------


class TestPyprojectFields:
    """Internal-correct pyproject: not a PyPI render, but must build
    and install via pip install -e."""

    def test_pyproject_has_name_and_version(self, pyproject_data: dict):
        assert pyproject_data["project"]["name"] == "kb-tools"
        assert isinstance(pyproject_data["project"]["version"], str)
        assert re.match(r"^\d+\.\d+\.\d+", pyproject_data["project"]["version"])

    def test_pyproject_has_requires_python(self, pyproject_data: dict):
        assert pyproject_data["project"]["requires-python"] == ">=3.11"

    def test_pyproject_has_entry_point(self, pyproject_data: dict):
        scripts = pyproject_data["project"]["scripts"]
        assert scripts["kb"] == "kb.cli:main"

    def test_pyproject_dependencies_present(self, pyproject_data: dict):
        deps = pyproject_data["project"]["dependencies"]
        # Just check the core runtime deps; loose equality to allow
        # version specifier tweaks.
        names = {re.split(r"[<>=!~]", d)[0].strip() for d in deps}
        for required in ("click", "flask", "pypdf", "pyyaml"):
            assert required in names, f"{required} missing from dependencies"


# ---------------------------------------------------------------------------
# Repo hygiene — nothing publish-shaped should be tracked
# ---------------------------------------------------------------------------


class TestRepoHygiene:
    def test_no_egg_info_tracked(self):
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        offenders = [
            line for line in out.stdout.splitlines()
            if "egg-info" in line or line.endswith(".egg")
        ]
        assert not offenders, f"egg-info / .egg tracked: {offenders}"

    def test_no_build_artifacts_tracked(self):
        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        # MANIFEST.in is a SOURCE FILE we author (controls sdist contents)
        # and is intentionally tracked. MANIFEST (no .in) is the auto-generated
        # legacy artifact and must not be tracked.
        offenders = [
            line for line in out.stdout.splitlines()
            if line.startswith(("build/", "dist/")) or line == "MANIFEST"
        ]
        assert not offenders, f"build artifacts tracked: {offenders}"

    def test_gitignore_catches_packaging_artifacts(self):
        text = GITIGNORE_PATH.read_text()
        for pattern in ("*.egg-info", "build/", "dist/", "MANIFEST"):
            assert pattern in text, f"{pattern} missing from .gitignore"

    def test_no_release_workflow(self):
        """Per GOVERNANCE.md §4: no release/publish workflow file."""
        assert not (REPO_ROOT / ".github" / "workflows" / "release.yml").exists()

    def test_readme_install_section_is_git_clone_first(self):
        """Quick Demo / install instructions lead with git clone, not pip install.

        'pip install kb-tools' on its own (without -e) implies a public package
        install — banned by GOVERNANCE.md §1-3. 'pip install -e \".[dev]\"'
        (editable from source) is fine.
        """
        text = README_PATH.read_text()
        # Find the install block
        m = re.search(r"##\s*(?:インストール|Installation)\s*(.*?)\n##\s", text, re.DOTALL)
        assert m, "install section not found in README"
        block = m.group(1)
        # Negative mentions like 'pip install kb-tools でのインストールもできません'
        # are OK (we're saying we DON'T do that). Positive install instructions
        # would be 'pip install kb-tools' NOT followed by ' -e' or any flag.
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("pip install", "$ pip install")):
                continue
            # Skip if preceded by '#' (commented out) or is the negation
            if "PyPI" in line or "できません" in line or "できない" in line:
                continue
            # The actual install command. 'pip install kb-tools' (no -e) is
            # what we ban.
            if re.search(r"\bpip install kb-tools\b", line) and "-e" not in line:
                raise AssertionError(
                    f"README install section has 'pip install kb-tools'"
                    f" (no -e) — implies a public package install."
                    f" Use 'pip install -e \\\".[dev]\\\"' for source install."
                    f" Offending line: {line!r}"
                )


# ---------------------------------------------------------------------------
# Local build
# ---------------------------------------------------------------------------


class TestLocalBuild:
    def test_build_wheel_succeeds_locally(
        self, built_wheel: Path, pyproject_version: str
    ):
        assert built_wheel.exists()
        assert built_wheel.suffix == ".whl"
        # The wheel filename embeds the project + version, e.g.
        # 'kb_tools-0.2.0-py3-none-any.whl'
        assert pyproject_version in built_wheel.name
        assert built_wheel.name.startswith("kb_tools-")


# ---------------------------------------------------------------------------
# Fresh-venv install
# ---------------------------------------------------------------------------


class TestFreshVenvInstall:
    """This is the test that matters: prove that a wheel install in a
    clean venv produces a working 'kb' command. Catches:
    - missing entry point
    - missing package data
    - broken console_scripts
    - dependency resolution failure
    """

    def test_kb_entry_point_reports_version(
        self, wheel_and_venv: Path, pyproject_version: str
    ):
        result = subprocess.run(
            [str(wheel_and_venv / "bin" / "kb"), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"kb --version failed:\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
        assert pyproject_version in result.stdout, (
            f"expected {pyproject_version} in {result.stdout!r}"
        )

    def test_kb_help_works_after_wheel_install(self, wheel_and_venv: Path):
        result = subprocess.run(
            [str(wheel_and_venv / "bin" / "kb"), "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        # Quick spot-check: the new commands from Phase 13/14 should
        # be in --help output.
        out = result.stdout
        for cmd in ("init", "add", "search", "evaluate", "improve"):
            assert cmd in out, f"kb --help missing '{cmd}'"

    def test_kb_init_add_search_after_wheel_install(
        self, wheel_and_venv: Path, tmp_path: Path
    ):
        kb = wheel_and_venv / "bin" / "kb"
        # Run inside an empty tmp dir so kb init makes a fresh bucket.
        cwd = tmp_path / "smoke-bucket"
        cwd.mkdir()

        # kb init
        r = subprocess.run(
            [str(kb), "init", "."], cwd=cwd, capture_output=True, text=True, timeout=30
        )
        assert r.returncode == 0, f"kb init failed: {r.stderr}"

        # kb add
        r = subprocess.run(
            [str(kb), "add", "--title", "smoke", "--content", "hello kb wheel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert r.returncode == 0, f"kb add failed: {r.stderr}"

        # kb search
        r = subprocess.run(
            [str(kb), "search", "hello"], cwd=cwd, capture_output=True, text=True, timeout=30
        )
        assert r.returncode == 0, f"kb search failed: {r.stderr}"
        assert "smoke" in r.stdout, f"kb search did not find the doc: {r.stdout!r}"


# ---------------------------------------------------------------------------
# Optional: the full slow install-smoke path (build + venv + 4 sub-calls).
# Marked slow so it can be opted out: pytest -m 'not slow'.
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestFullInstallSmoke:
    def test_full_install_smoke(self, wheel_and_venv: Path, tmp_path: Path):
        # Same as the fast TestFreshVenvInstall.test_kb_init_add_search_*,
        # but kept under a slow marker for environments that want to skip
        # the venv creation.
        kb = wheel_and_venv / "bin" / "kb"
        cwd = tmp_path / "smoke-bucket-2"
        cwd.mkdir()
        subprocess.run([str(kb), "init", "."], cwd=cwd, check=True, capture_output=True)
        subprocess.run(
            [str(kb), "add", "--title", "slow", "--content", "smoke"],
            cwd=cwd, check=True, capture_output=True
        )
        subprocess.run(
            [str(kb), "search", "smoke"], cwd=cwd, check=True, capture_output=True
        )
