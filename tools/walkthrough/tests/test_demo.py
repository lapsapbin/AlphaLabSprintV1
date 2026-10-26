"""Synthetic file/path guards and code-source-only checks; no financial fixtures."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).resolve().parents[1] / "run_demo.py"
spec = importlib.util.spec_from_file_location("demo_runner", RUNNER)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class SyntheticGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="synthetic-demo-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "demo"
        self.root.mkdir()
        self.file = self.root / "SYNTHETIC.txt"
        self.raw = b"SYNTHETIC teaching fixture, no financial observations.\n"
        self.file.write_bytes(self.raw)
        self.expected = {self.file.name: demo.digest(self.raw)}

    def test_valid_and_missing_inputs(self):
        self.assertEqual(demo.verify_inputs(self.root, self.expected)[self.file.name]["bytes"], len(self.raw))
        self.file.unlink()
        with self.assertRaisesRegex(demo.DemoError, "Missing accepted"):
            demo.verify_inputs(self.root, self.expected)

    def test_tamper_is_refused_without_repair(self):
        changed = b"SYNTHETIC changed bytes"
        self.file.write_bytes(changed)
        with self.assertRaisesRegex(demo.DemoError, "SHA-256 mismatch"):
            demo.verify_inputs(self.root, self.expected)
        self.assertEqual(self.file.read_bytes(), changed)

    def test_input_escape_and_symlink_are_refused(self):
        for name in ["../escape.txt", str(self.file)]:
            with self.assertRaisesRegex(demo.DemoError, "Unsafe input"):
                demo.verify_inputs(self.root, {name: "0" * 64})
        link = self.root / "link.txt"
        link.symlink_to(self.file)
        with self.assertRaisesRegex(demo.DemoError, "Symlink input"):
            demo.verify_inputs(self.root, {link.name: demo.digest(self.raw)})

    def test_existing_output_preserved(self):
        out = self.base / "previous-run"
        out.mkdir()
        old = out / "old-evidence.txt"
        old.write_bytes(self.raw)
        with self.assertRaisesRegex(demo.DemoError, "already exists"):
            demo.safe_output(self.root, out)
        self.assertEqual(old.read_bytes(), self.raw)

    def test_output_boundaries_and_symlinks(self):
        for relative in ["outputs/run", "reports/run", "notebooks/run"]:
            with self.assertRaisesRegex(demo.DemoError, "outside"):
                demo.safe_output(self.root, self.root / relative)
        other = self.base / "other-project"
        other.mkdir()
        (other / "PROJECT_SPEC.md").write_text("SYNTHETIC project marker")
        with self.assertRaisesRegex(demo.DemoError, "marker tree"):
            demo.safe_output(self.root, other / "reports/run")
        alias = self.base / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(demo.DemoError, "Symlink"):
            demo.safe_output(self.root, alias / "new")

    def test_new_external_output_is_only_validated_not_created(self):
        out = self.base / "fresh/run"
        self.assertEqual(demo.safe_output(self.root, out), out)
        self.assertFalse(out.exists())
        self.assertEqual(self.file.read_bytes(), self.raw)

    def test_production_network_and_write_sources_refused(self):
        for code in ["import alphalab", "from alphalab.cli import main", "import subprocess",
                     "import urllib.request", "p.write_text('x')", "os.system('x')", "exec('x')"]:
            with self.subTest(code=code), self.assertRaises(demo.DemoError):
                demo.check_sources([code])
        self.assertEqual(demo.check_sources(["import math\nassert math.sqrt(4) == 2"]), ["math"])

    def test_failure_record_does_not_overwrite_synthetic_source(self):
        # Stubs simulate a notebook-tool failure, not a real kernel or result.
        nb = self.root / demo.NOTEBOOK
        nb.parent.mkdir()
        raw = json.dumps({"cells": [], "metadata": {"label": "SYNTHETIC"}}).encode()
        nb.write_bytes(raw)
        runner = self.base / "synthetic_runner.py"
        runner.write_text("# SYNTHETIC runner identity")
        manifest = self.base / "demo_inputs.json"
        blob = json.dumps({"files": {demo.NOTEBOOK: demo.digest(raw)}}).encode()
        manifest.write_bytes(blob)
        def fail(*args, **kwargs):
            raise RuntimeError("SYNTHETIC tool failure")
        modules = {"nbformat": SimpleNamespace(reads=fail),
                   "nbclient": SimpleNamespace(NotebookClient=object),
                   "jupyter_client": SimpleNamespace(KernelManager=object)}
        out = self.base / "failed-run"
        with patch.object(demo, "__file__", str(runner)), patch.object(demo, "MANIFEST_SHA256", demo.digest(blob)), patch.dict(sys.modules, modules):
            self.assertEqual(demo.execute(self.root, out), 1)
        record = json.loads((out / "execution.json").read_text())
        self.assertEqual(record["exit"], 1)
        self.assertIn("SYNTHETIC tool failure", record["failure_traceback"])
        self.assertEqual(nb.read_bytes(), raw)
        self.assertFalse((out / "executed_walkthrough.ipynb").exists())


class TeachingSourceStaticCheck(unittest.TestCase):
    def test_teaching_code_source_only(self):
        # Saved real outputs are NOT assertions, test fixtures or executed cells.
        path = RUNNER.parents[2] / "notebooks/01_research_walkthrough.ipynb"
        document = json.loads(path.read_text(encoding="utf-8"))
        sources = ["".join(c["source"]) for c in document["cells"] if c["cell_type"] == "code"]
        self.assertTrue(sources)
        demo.check_sources(sources)


if __name__ == "__main__":
    unittest.main()
