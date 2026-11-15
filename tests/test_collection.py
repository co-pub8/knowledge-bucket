"""Regression tests: the suite must collect without the optional dependencies.

The package is meant to be usable straight from a source checkout — see
``[tool.pytest.ini_options] pythonpath`` in ``pyproject.toml``, which makes
``import kb`` resolve without an editable install. The same principle has to
hold for the third-party dependencies: an environment that does not install
``click`` / ``flask`` / ``pypdf`` / ``pyarrow`` must degrade to *skipped*
tests, never to a collection error. A collection error aborts the whole
pytest run, so it is reported as a failing run even though no assertion
failed.

These tests simulate such an environment by blocking the imports in a
subprocess and asserting that collection still succeeds.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Plugin injected into the child pytest run via ``-p``. It installs a meta
# path finder that makes the listed top-level packages unimportable.
BLOCKER_PLUGIN = '''
import sys
from importlib.abc import MetaPathFinder

BLOCKED = {"click", "flask", "pypdf", "pyarrow"}


class _Blocker(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLOCKED:
            raise ImportError(f"blocked for test purposes: {fullname}")
        return None


sys.meta_path.insert(0, _Blocker())
'''

# Modules whose top-level import needs one of the blocked packages.
DEPENDENT_MODULES = [
    "tests/test_cli.py",
    "tests/test_export.py",
    "tests/test_install.py",
    "tests/test_storage.py",
    "tests/test_web.py",
    "tests/test_parsers_pdf.py",
]

# A module that needs none of the blocked packages. It is collected together
# with the dependent ones so that a successful collection also yields real
# tests (pytest exits 5 when nothing at all is collected).
NEUTRAL_MODULE = "tests/test_core.py"


def _pytest_without_optional_dependencies(tmp_path, modules, *args):
    """Run pytest in a child process where the optional deps are unimportable."""
    plugin_dir = tmp_path / "blocked_deps"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "blocked_deps.py").write_text(BLOCKER_PLUGIN)

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(plugin_dir)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "blocked_deps",
            "-p",
            "no:cacheprovider",
            *args,
            *modules,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result


class TestCollectionWithoutOptionalDependencies:
    def test_dependent_modules_collect_without_optional_dependencies(self, tmp_path):
        """A missing click/flask/pypdf/pyarrow must not abort collection."""
        result = _pytest_without_optional_dependencies(
            tmp_path, [*DEPENDENT_MODULES, NEUTRAL_MODULE], "--collect-only", "-q"
        )
        assert result.returncode == 0, (
            "pytest collection failed without the optional dependencies:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "ERROR collecting" not in result.stdout, result.stdout

    def test_health_module_collects_without_flask_and_click(self, tmp_path):
        """kb.health imports flask/click lazily, inside the test bodies.

        Those classes must be skipped instead of failing when the packages
        are missing, so the module still has to collect and run.
        """
        result = _pytest_without_optional_dependencies(
            tmp_path, ["tests/test_health.py"], "-q"
        )
        assert result.returncode == 0, (
            "pytest failed without flask/click:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "ERROR collecting" not in result.stdout, result.stdout
