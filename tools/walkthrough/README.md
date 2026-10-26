# Read-only research walkthrough

One [teaching Notebook](../../notebooks/01_research_walkthrough.ipynb) displays accepted results and labeled synthetic examples. Saved outputs can be read without execution. No production package is imported. The owner has authorized this complete research presentation; [rights and source-data exclusions](../../docs/RIGHTS_STATUS.md) remain explicit. No additional software license is granted.

## Separate environment and explicit paths

Set DEMO_ROOT to the absolute public repository path, WORK to a new external tools/run directory outside every PROJECT_SPEC-marked tree, and PYTHON312 to an existing verified Python 3.12 executable. The actual validation uses Python 3.12.13, a separate dependency environment and this unchanged demo lock. It does not install into the frozen research environment.

```sh
export DEMO_ROOT="/absolute/path/to/AlphaLabSprintV1"
export WORK="/absolute/path/to/new-demo-work"
export PYTHON312="/absolute/path/to/verified/python3.12"
export UV_PROJECT_ENVIRONMENT="$WORK/environment"
export UV_CACHE_DIR="$WORK/cache"
export PYTHONDONTWRITEBYTECODE=1
uv sync --project "$DEMO_ROOT/tools/walkthrough" --frozen --python "$PYTHON312"
"$UV_PROJECT_ENVIRONMENT/bin/python" -B "$DEMO_ROOT/tools/walkthrough/run_demo.py" --root "$DEMO_ROOT" --output-dir "$WORK/run-01"
```

Use the standalone tool project, never a root dependency sync. Dependency installation may access the package registry; it does not download financial data. Actual PUB-04 validation creates a new dependency environment using an already independently managed base Python on the same Mac. New OS/machine compatibility is unverified. The execution command works from outside the repository directory.

The output must not exist. It contains executed_walkthrough.ipynb (a run artifact), execution.json and isolated runtime files. Inputs remain unchanged. Runtime records contain local paths and are private by default; do not copy them into a public repository. Relative documentation links in run artifacts retain the source Notebook context; use the teaching source for navigation.

The [input manifest](demo_inputs.json) pins eleven inputs: source Notebook and public specification marker; five unchanged summaries, three explicitly labeled public display derivative manifests and one unchanged PNG. Original private freeze manifests are not replaced. The runner checks every hash before kernel start, refuses symlinks/path escapes/existing outputs/project-tree destinations, and explicitly cleans the kernel connection file. Errors never download, rebuild, repair or invoke research. This is a process guard for a trusted fixed Notebook, not an arbitrary-code security sandbox.

## Small synthetic/static checks

```sh
"$UV_PROJECT_ENVIRONMENT/bin/python" -B -m unittest discover -s "$DEMO_ROOT/tools/walkthrough/tests" -v
```

Nine checks use labeled synthetic temporary files and the Notebook's code-source fields only. They do not consume saved financial output as fixtures, execute the Notebook, install research packages or run root tests. The workflow uses the same unittest discovery from repository root. See the [Synthetic demo guards workflow](https://github.com/lapsapbin/AlphaLabSprintV1/actions/workflows/demo-ci.yml) for its actual remote status. This workflow performs no research, deployment or secret-dependent step.

See [report](../../reports/final_report.md), [reproduction limits](../../docs/REPRODUCIBILITY.md) and [source map](../../PUBLIC_SOURCE_MAP.json). Historical private QA helpers and operational evidence are deliberately excluded; the default launcher is run_demo.py.
