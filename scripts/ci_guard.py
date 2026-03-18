from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable


WORKFLOW_PATH = Path(".github/workflows/test.yml")
SDK_PYPROJECT_PATH = Path("sdk/pyproject.toml")
SUPPORTED_MIN_PYTHON = "3.10"


def _ensure(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _read_text(path: Path) -> str:
    _ensure(path.exists(), f"Expected file to exist: {path}")
    return path.read_text(encoding="utf-8")


def _extract_sdk_matrix_versions(workflow_text: str) -> list[str]:
    matrix_match = re.search(
        r"test-sdk:[\s\S]*?matrix:\s*[\r\n](?:.*?\r?\n)*?\s*python-version:\s*\[(.*?)\]",
        workflow_text,
        flags=re.MULTILINE,
    )
    _ensure(matrix_match is not None, "Could not parse SDK test matrix from workflow")

    values = matrix_match.group(1)
    return [
        token.strip().strip("'\"\n\r ")
        for token in values.split(",")
        if token.strip()
    ]


def _extract_sdk_requires_python(pyproject_text: str) -> str:
    requirement_match = re.search(r"requires-python\s*=\s*\"([^\"]+)\"", pyproject_text)
    _ensure(
        requirement_match is not None,
        "Could not parse requires-python from sdk/pyproject.toml",
    )
    return requirement_match.group(1).strip()


def _extract_min_python_version(requires_python: str) -> tuple[int, int]:
    match = re.search(r">=([0-9]+\.[0-9]+)", requires_python)
    _ensure(match is not None, f"Unexpected requires-python spec: {requires_python}")
    return _python_key(match.group(1))


def _python_key(version: str) -> tuple[int, int]:
    parts = version.split(".")
    _ensure(
        len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit(),
        f"Invalid python version format: {version}",
    )
    return int(parts[0]), int(parts[1])


def _assert_supported_matrix(versions: list[str]) -> None:
    version_tuples = [_python_key(v) for v in versions]
    _ensure(
        any(v >= _python_key(SUPPORTED_MIN_PYTHON) for v in version_tuples),
        "SDK CI matrix should include at least one supported Python version",
    )
    for version in versions:
        _ensure(
            _python_key(version) >= _python_key(SUPPORTED_MIN_PYTHON),
            f"SDK CI matrix includes unsupported Python version {version}",
        )


def _assert_pyproject_supports_ci_versions(requires_python: str, versions: Iterable[str]) -> None:
    min_supported = _python_key(SUPPORTED_MIN_PYTHON)
    declared_min = _extract_min_python_version(requires_python)
    _ensure(
        declared_min <= min_supported,
        f"SDK requires-python ({requires_python}) must include {SUPPORTED_MIN_PYTHON}",
    )
    for version in versions:
        _ensure(
            _python_key(version) >= min(declared_min, min_supported),
            f"CI version {version} below package floor {requires_python}",
        )


def main() -> int:
    workflow_text = _read_text(WORKFLOW_PATH)
    sdk_versions = _extract_sdk_matrix_versions(workflow_text)

    pyproject_text = _read_text(SDK_PYPROJECT_PATH)
    requires_python = _extract_sdk_requires_python(pyproject_text)

    _assert_supported_matrix(sdk_versions)
    _assert_pyproject_supports_ci_versions(requires_python, sdk_versions)

    print("CI guard passed")
    print(f"  SDK requires-python: {requires_python}")
    print(f"  SDK matrix versions: {', '.join(sdk_versions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
