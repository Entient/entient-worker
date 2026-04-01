#!/usr/bin/env python3
"""Job handlers — execution logic for each job type.

Each handler receives (spec, job_id) and returns (result_dict, [files_to_upload]).
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────

WORKER_DIR = Path(__file__).parent
REPOS_DIR = WORKER_DIR / "repos"
INTERCEPTOR_DIR = REPOS_DIR / "entient-interceptor"
AGENT_DIR = REPOS_DIR / "entient-agents"
BANK_DIR = Path(os.path.expanduser("~/.entient/bank"))


# ── COMPILE: run op_factory with JSON specs ───────────────────────

def handle_compile(spec, job_id):
    """Generate operators from JSON specs. Pure stdlib, no deps."""
    # spec is a list of operator definitions
    if isinstance(spec, dict):
        spec = [spec]

    # Use op_factory if available, otherwise inline
    op_factory = INTERCEPTOR_DIR / "tools" / "op_factory.py"
    if op_factory.exists():
        # Write spec to temp file, run factory
        spec_file = WORKER_DIR / f"_spec_{job_id}.json"
        spec_file.write_text(json.dumps(spec), encoding="utf-8")
        try:
            result = subprocess.run(
                [sys.executable, str(op_factory), str(spec_file)],
                capture_output=True, text=True, timeout=120,
                cwd=str(INTERCEPTOR_DIR),
            )
            print(result.stdout)
            if result.stderr:
                print(result.stderr)
        finally:
            spec_file.unlink(missing_ok=True)
    else:
        # Inline fallback: generate ops directly
        _inline_compile(spec)

    # Collect generated files for upload
    files = []
    for s in spec:
        name = s.get("name", "")
        op_file = BANK_DIR / f"op_{name}.py"
        if op_file.exists():
            files.append(op_file)

    return {
        "specs_given": len(spec),
        "files_generated": len(files),
        "names": [s.get("name") for s in spec],
    }, files


def _inline_compile(specs):
    """Fallback: generate ops without op_factory.py."""
    import ast
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        name = spec.get("name", "")
        if not name:
            continue
        path = BANK_DIR / f"op_{name}.py"
        if path.exists():
            continue
        keywords = spec.get("keywords", [])
        bigrams = spec.get("bigrams", [])
        cluster = spec.get("cluster", "general")
        idiom = spec.get("idiom", "direct-return")
        template = spec.get("template", f"def {name}(**kwargs):\n    pass\n")
        desc = spec.get("desc", f"Auto-generated: {name}")
        code = f'''from entient_interceptor.core import ParamOp, register

register(ParamOp(
    name={name!r},
    description={desc!r},
    primary_keywords={keywords!r},
    secondary_keywords=[],
    bigrams={bigrams!r},
    cluster={cluster!r},
    structural_idiom={idiom!r},
    params={{}},
    param_extractors={{}},
    template={template!r},
))
'''
        try:
            ast.parse(code)
            path.write_text(code, encoding="utf-8")
            print(f"  + {name}")
        except Exception as e:
            print(f"  X {name}: {e}")


# ── MINE: run mining on GitHub repos ──────────────────────────────

def handle_mine(spec, job_id):
    """Mine GitHub repos for structural patterns."""
    mine_script = INTERCEPTOR_DIR / "tools" / "mine_eye_bulk.py"
    if not mine_script.exists():
        raise FileNotFoundError(f"Mining script not found: {mine_script}")

    repo_set_id = spec.get("repo_set_id")
    args = [sys.executable, str(mine_script)]
    if repo_set_id is not None:
        args.extend(["--sets", str(repo_set_id)])
    else:
        args.append("--all")

    result = subprocess.run(
        args, capture_output=True, text=True, timeout=7200,  # 2h max
        cwd=str(INTERCEPTOR_DIR),
    )
    print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    if result.returncode != 0 and result.stderr:
        print(f"STDERR: {result.stderr[-1000:]}")

    # Check for harvest DB
    files = []
    harvest = AGENT_DIR / "pretrain_harvest.db"
    if harvest.exists():
        files.append(harvest)

    return {
        "repo_set_id": repo_set_id,
        "exit_code": result.returncode,
        "output_tail": result.stdout[-500:],
    }, files


# ── RETRAIN: retrain router weights from outcomes ─────────────────

def handle_retrain(spec, job_id):
    """Retrain the logistic router from outcome data."""
    train_script = INTERCEPTOR_DIR / "tools" / "train_from_outcomes.py"
    if not train_script.exists():
        raise FileNotFoundError(f"Training script not found: {train_script}")

    args = [sys.executable, str(train_script), "train", "--save"]
    epochs = spec.get("epochs", 5)
    if epochs != 5:
        args.extend(["--epochs", str(epochs)])

    result = subprocess.run(
        args, capture_output=True, text=True, timeout=1800,  # 30min max
        cwd=str(INTERCEPTOR_DIR),
    )
    print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)

    # Collect trained weights for upload
    files = []
    weights_dir = INTERCEPTOR_DIR / "weights"
    current = weights_dir / "current.json"
    if current.exists():
        files.append(current)
    defaults = INTERCEPTOR_DIR / "entient_interceptor" / "defaults.py"
    if defaults.exists():
        files.append(defaults)

    return {
        "exit_code": result.returncode,
        "output_tail": result.stdout[-500:],
    }, files


# ── CROSSINDEX: refresh shape-genome cross-index ──────────────────

def handle_crossindex(spec, job_id):
    """Run shape-genome cross-index refresh."""
    script = INTERCEPTOR_DIR / "tools" / "shape_genome_crossindex.py"
    if not script.exists():
        raise FileNotFoundError(f"Cross-index script not found: {script}")

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=7200,  # 2h max
        cwd=str(INTERCEPTOR_DIR),
    )
    print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)

    return {
        "exit_code": result.returncode,
        "output_tail": result.stdout[-500:],
    }, []


# ── COVERAGE: run coverage metrics ────────────────────────────────

def handle_coverage(spec, job_id):
    """Run coverage measurement and report."""
    script = INTERCEPTOR_DIR / "tools" / "coverage_metrics.py"
    if not script.exists():
        raise FileNotFoundError(f"Coverage script not found: {script}")

    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=300,
        cwd=str(INTERCEPTOR_DIR),
    )
    print(result.stdout)

    return {
        "exit_code": result.returncode,
        "output": result.stdout,
    }, []


# ── Handler Registry ──────────────────────────────────────────────

HANDLERS = {
    "compile": handle_compile,
    "mine": handle_mine,
    "retrain": handle_retrain,
    "crossindex": handle_crossindex,
    "coverage": handle_coverage,
}
