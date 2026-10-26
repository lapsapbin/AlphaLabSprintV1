"""Execute one hash-bound teaching notebook; display + synthetic only.

This is a reproducibility/process guard, not a sandbox for untrusted notebooks.
The production package and the historical private QA helper are never imported.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
import traceback

MANIFEST_SHA256 = "d4bd43f9ddafc12ad964f7591aa58f80d66b9a99d8250f81c7a35edf2a9f62ba"
NOTEBOOK = "notebooks/01_research_walkthrough.ipynb"
ALLOWED_IMPORTS = {"pathlib", "csv", "hashlib", "io", "json", "os", "html",
                   "IPython.display", "decimal", "math", "statistics"}
BLOCKED_CALLS = {"exec", "eval", "compile", "__import__", "open", "system", "run",
                 "Popen", "write_text", "write_bytes", "unlink", "mkdir", "remove",
                 "rename", "replace", "rmdir", "rmtree", "touch"}


class DemoError(ValueError):
    """Controlled refusal before reading or writing outside the demo contract."""


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def verify_inputs(root, expected):
    """Reusable file gate. Tests supply only explicitly synthetic fixtures."""
    root = Path(root).resolve(strict=True)
    records = {}
    for relative, wanted in expected.items():
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise DemoError("Unsafe input path: " + relative)
        path = root / rel
        if any(p.is_symlink() for p in [path, *path.parents] if p != root and root in p.parents):
            raise DemoError("Symlink input refused: " + relative)
        if not path.is_file():
            raise DemoError("Missing accepted file: " + relative + "; no download or rebuild")
        raw = path.read_bytes()
        actual = digest(raw)
        if actual != wanted:
            raise DemoError("SHA-256 mismatch: " + relative)
        records[relative] = {"sha256": actual, "bytes": len(raw)}
    return records


def safe_output(root, output):
    """Require a new external directory, also excluding other project trees."""
    root = Path(root).resolve(strict=True)
    requested = Path(output).expanduser().absolute()
    if requested.exists() or requested.is_symlink():
        raise DemoError("Output already exists; refusal preserves prior evidence")
    if any(p.is_symlink() for p in requested.parents):
        raise DemoError("Symlink output ancestor refused")
    output = requested.resolve()
    if output == root or root in output.parents or output in root.parents:
        raise DemoError("Output must be outside the demo/project root")
    # Also refuse a sibling private project's reports/outputs, not just this demo.
    for parent in output.parents:
        if (parent / "PROJECT_SPEC.md").is_file():
            raise DemoError("Output must be outside every project marker tree")
    return output


def check_sources(sources):
    """Static review of code source only; never execute source in this check."""
    imports = set()
    for source in sources:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
            elif isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if name in BLOCKED_CALLS:
                    raise DemoError("Disallowed notebook call: " + name)
            elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                raise DemoError("Dunder access refused")
    if not imports <= ALLOWED_IMPORTS:
        raise DemoError("Disallowed notebook imports: " + str(sorted(imports - ALLOWED_IMPORTS)))
    return sorted(imports)


def visible_outputs(notebook):
    result = []
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            result.append([{k: v for k, v in out.items() if k in {"output_type", "data", "text", "name"}}
                           for out in cell.get("outputs", [])])
    return result


def exclusive_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def execute(root, output):
    started = time.monotonic()
    record = {"command": [sys.executable, "-B", *sys.argv], "cwd": str(Path.cwd()),
              "started_utc": utc(), "scope": "display + synthetic only",
              "python": sys.version, "platform": platform.platform(),
              "executable": sys.executable, "base_executable": sys._base_executable,
              "real_executable": str(Path(sys.executable).resolve()),
              "prefix": sys.prefix, "base_prefix": sys.base_prefix,
              "runner_sha256": digest(Path(__file__).read_bytes()),
              "formal_research_runs": 0, "formal_oos_runs": 0}
    # Before any output creation or kernel start, verify the complete explicit list.
    output = safe_output(root, output)
    root = Path(root).expanduser().resolve(strict=True)
    raw = Path(__file__).with_name("demo_inputs.json").read_bytes()
    if digest(raw) != MANIFEST_SHA256:
        raise DemoError("Demo input manifest SHA-256 mismatch")
    manifest = json.loads(raw)
    before = verify_inputs(root, manifest["files"])
    original = json.loads((root / NOTEBOOK).read_text(encoding="utf-8"))
    record["static_imports"] = check_sources(["".join(c["source"]) for c in original["cells"] if c["cell_type"] == "code"])
    output.mkdir(parents=True, exist_ok=False)
    record.update(root=str(root), output=str(output), inputs_before=before,
                  input_manifest_sha256=digest(raw))
    status = 1
    try:
        import nbformat
        from nbclient import NotebookClient
        from jupyter_client import KernelManager

        record["installed_versions"] = dict(sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions()))
        nb = nbformat.reads((root / NOTEBOOK).read_text(encoding="utf-8"), as_version=4)
        nbformat.validate(nb)
        expected_outputs = visible_outputs(nb)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", ALPHALAB_ROOT=str(root))
        for key in ("IPYTHONDIR", "JUPYTER_RUNTIME_DIR", "JUPYTER_CONFIG_DIR", "JUPYTER_DATA_DIR", "MPLCONFIGDIR"):
            folder = output / "runtime" / key.lower()
            folder.mkdir(parents=True)
            env[key] = str(folder)
        connection_file = output / "runtime" / "kernel.json"
        manager = KernelManager(kernel_name="python3", connection_file=str(connection_file))
        manager.kernel_spec.argv[0] = sys.executable
        record["fresh_kernel_argv"] = manager.kernel_spec.argv
        record["connection_file"] = str(connection_file)
        record["explicit_kernel_cleanup"] = True
        NotebookClient(nb, km=manager, timeout=120, allow_errors=False,
                       resources={"metadata": {"path": str(output)}}).execute(env=env, cleanup_kc=True)
        record["connection_file_removed_after_cleanup"] = not connection_file.exists()
        if connection_file.exists():
            raise DemoError("Kernel connection file remained after cleanup")
        nbformat.validate(nb)
        if visible_outputs(nb) != expected_outputs:
            raise DemoError("Display outputs differ from accepted saved notebook outputs")
        after = verify_inputs(root, manifest["files"])
        if after != before:
            raise DemoError("Inputs changed during execution")
        nb.metadata["publication_run_artifact"] = {"teaching_source": NOTEBOOK,
            "source_sha256": before[NOTEBOOK]["sha256"], "scope": "display + synthetic only"}
        with (output / "executed_walkthrough.ipynb").open("x", encoding="utf-8") as stream:
            stream.write(nbformat.writes(nb))
        record.update(inputs_after=after, inputs_unchanged=True,
                      code_cells_executed=sum(c.cell_type == "code" for c in nb.cells),
                      visible_outputs_match_accepted=True, cells=len(nb.cells))
        status = 0
    except Exception:
        record["failure_traceback"] = traceback.format_exc()
    finally:
        record.update(exit=status, ended_utc=utc(), elapsed_seconds=time.monotonic() - started)
        record["artifacts"] = {p.name: {"bytes": p.stat().st_size, "sha256": digest(p.read_bytes())}
                               for p in output.iterdir() if p.is_file()}
        exclusive_json(output / "execution.json", record)
    print(json.dumps({"exit": status, "scope": record["scope"], "record": str(output / "execution.json"),
                      "elapsed_seconds": record["elapsed_seconds"]}))
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="Explicit demo/project root")
    parser.add_argument("--output-dir", required=True, type=Path, help="New directory outside project trees")
    args = parser.parse_args()
    try:
        return execute(args.root, args.output_dir)
    except (DemoError, OSError, ValueError) as error:
        print(json.dumps({"exit": 1, "scope": "display + synthetic only", "utc": utc(),
                          "error": str(error), "kernel_started": False}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
