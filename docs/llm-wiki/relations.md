# Repository relations
Repository: knowledge-bucket

## ai-hub
- Status: confirmed
- Relationship: subject/provider — ai-hub's verification harness consumes this repository as the candidate under test (it copies a worktree, runs `pytest` against it and binds the result as acceptance evidence); this repository owns the `kb` package, its on-disk bucket format and its test suite, and ships the configuration that makes the suite collectable in a foreign environment.
- Responsibility: knowledge-bucket owns the package layout (`src/` layout), the pytest configuration (`[tool.pytest.ini_options]`) and the demo fixtures that the harness copies; ai-hub owns the verification environment, the candidate-binding rules and the selector-to-outcome matching.
- Canonical sources: knowledge-bucket — `SYSTEM_CONSTITUTION.md`, `PURPOSE.md`, `docs/GOVERNANCE.md`, `pyproject.toml`; ai-hub — `tools/eval/verification_workspace.py`, `tools/eval/verification_copy.py`, `tools/eval/test_evidence.py`.
- Change rule: when knowledge-bucket changes its test layout, packaging layout or any file that a test run rewrites, inspect ai-hub's `tools/eval/verification_workspace.py` (a tracked file changed during the run invalidates the candidate binding, `exit_code -2`, `verification_candidate_binding_changed`) and `tools/eval/test_evidence.py` (acceptance criteria must name function-level pytest node ids — a class-level selector such as `tests/test_core.py::TestUlid` matches no case and is reported as `matched=0`).
- Evidence: knowledge-bucket:pyproject.toml sha256:ffd34a03677622140f9cbcfab6713fbac8be06c743ae4b79b995b2deaa330ae2
- Evidence: knowledge-bucket:.gitignore sha256:dc07d2ac23592a1f407115db75b5aeed5ea2e19353fbcf2ae5dcdb73a259cca7
- Evidence: knowledge-bucket:tests/test_release.py sha256:2cf67c8e47824b6b4b0f4578d575027acf8389c7ed2fbf13fd32ce1cdc2e3ca1
- Evidence: knowledge-bucket:examples/demo-bucket/config/kb.yml sha256:2e322797462762f884d9ef4c666d21240634bd99f41456faf5276c2c8e5113b7
- Evidence: ai-hub:tools/eval/test_evidence.py sha256:99e0da408391cdb0a26cc20891cf82d3a292809d0a77f5410001a959fc723bfc
- Evidence: ai-hub:tools/eval/verification_workspace.py sha256:aafa76498d851525e42a36b74f5fb7c7141332432b0c4227dfab13a95f09e3c9
- Evidence: ai-hub:tools/eval/verification_copy.py sha256:3b085b3cd3b54d9efffff99a09d6108bf366bf21cac4c0dcd9ba0715b7e41e8c
- Observation: ai-hub's `tools/eval/test_evidence.py::_matches` maps a pytest selector `file::Class::test` onto the junit `classname`/`name` pair; the junit classnames produced by this repository are `tests.<module>.<Class>` (e.g. `tests.test_core.TestUlid`), which is what the selectors in the recorded acceptance criteria use.
- Observation: the ai-hub deployment verification virtualenv has the `kb` package *not* installed, so `tests/test_core.py`, `tests/test_models.py` and `tests/test_ingest.py` failed to collect there until this repository set `[tool.pytest.ini_options] pythonpath = ["src"]`; the same virtualenv also lacks `click`, `flask` and `pyarrow`, so `tests/test_cli.py`, `tests/test_web.py`, `tests/test_export.py`, `tests/test_install.py` and `tests/test_storage.py` still cannot be collected there — that gap is environmental, not a defect of this repository.
- Follow-up: [ ] ai-hub — provisioning of the target repository's declared dependencies in the verification virtualenv; triggering change: acceptance verification of knowledge-bucket runs `pytest` in the deployment venv; remaining work: install `click`, `flask` and `pyarrow` (or install the candidate package with its dependencies) for the verification copy; completion condition: `python -m pytest tests/ -q --collect-only` in the deployment venv collects every test module without a collection error.
