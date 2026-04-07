#!/usr/bin/env python3
"""Job handlers — execution logic for each job type.

Each handler receives (spec, job_id) and returns (result_dict, [files_to_upload]).
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────

WORKER_DIR = Path(__file__).parent
REPOS_DIR = WORKER_DIR / "repos"
INTERCEPTOR_DIR = REPOS_DIR / "entient-interceptor"
AGENT_DIR = REPOS_DIR / "entient-agents"
ENTIENT_DIR = REPOS_DIR / "entient"
BANK_DIR = Path(os.path.expanduser("~/.entient/bank"))
DATA_DIR = Path(os.path.expanduser("~/.entient/v2"))
FORWARDS_DIR = Path(os.path.expanduser("~/.entient/forwards"))


# ── Capability Detection ──────────────────────────────────────────

def detect_capabilities():
    """Auto-detect what this machine can run based on available repos, DBs, and packages."""
    caps = ["compile"]  # Always available (stdlib only)
    missing = []

    # COVERAGE: needs outcome_ledger.db (no repo imports needed)
    ledger = DATA_DIR / "outcome_ledger.db"
    if ledger.exists():
        try:
            conn = sqlite3.connect(str(ledger))
            count = conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
            conn.close()
            if count > 0:
                caps.append("coverage")
            else:
                missing.append("coverage: outcome_ledger.db is empty")
        except Exception as e:
            missing.append(f"coverage: outcome_ledger.db unreadable ({e})")
    else:
        missing.append(f"coverage: {ledger} not found")

    # CROSSINDEX: needs shapes.db + genome_registry.db (no repo imports)
    shapes = DATA_DIR / "shapes.db"
    genomes = DATA_DIR / "genome_registry.db"
    if shapes.exists() and genomes.exists():
        try:
            conn = sqlite3.connect(str(shapes))
            sc = conn.execute("SELECT COUNT(*) FROM shapes").fetchone()[0]
            conn.close()
            if sc > 0:
                caps.append("crossindex")
            else:
                missing.append("crossindex: shapes.db is empty")
        except Exception as e:
            missing.append(f"crossindex: shapes.db unreadable ({e})")
    else:
        if not shapes.exists():
            missing.append(f"crossindex: {shapes} not found")
        if not genomes.exists():
            missing.append(f"crossindex: {genomes} not found")

    # MINE: needs entient-agent repo installed
    if AGENT_DIR.exists() and (AGENT_DIR / "entient_agent").exists():
        try:
            result = subprocess.run(
                [sys.executable, "-c", "from entient_agent.probe.engine import ProbeEngine"],
                capture_output=True, timeout=10)
            if result.returncode == 0:
                caps.append("mine")
            else:
                missing.append(f"mine: entient_agent import failed")
        except Exception as e:
            missing.append(f"mine: import check error ({e})")
    else:
        missing.append(f"mine: {AGENT_DIR / 'entient_agent'} not found")

    # SYNTHESIZE: needs entient-interceptor repo (API key optional — falls back to near_miss_sweep)
    near_miss_script = INTERCEPTOR_DIR / "tools" / "near_miss_sweep.py"
    bulk_script = INTERCEPTOR_DIR / "tools" / "bulk_synthesize.py"
    if near_miss_script.exists() or bulk_script.exists():
        caps.append("synthesize")
    else:
        missing.append(f"synthesize: neither near_miss_sweep.py nor bulk_synthesize.py found in {INTERCEPTOR_DIR / 'tools'}")

    # RETRAIN: needs entient-interceptor installed + outcome_ledger.db + bank ops
    train_script = INTERCEPTOR_DIR / "tools" / "train_from_outcomes.py"
    if train_script.exists() and ledger.exists():
        try:
            result = subprocess.run(
                [sys.executable, "-c", "from entient_interceptor.weight_layer import LogisticRouter"],
                capture_output=True, timeout=10)
            if result.returncode == 0:
                bank_count = len(list(BANK_DIR.glob("op_*.py"))) if BANK_DIR.exists() else 0
                if bank_count > 0:
                    caps.append("retrain")
                else:
                    missing.append(f"retrain: bank is empty ({BANK_DIR})")
            else:
                missing.append("retrain: entient_interceptor import failed")
        except Exception as e:
            missing.append(f"retrain: import check error ({e})")
    else:
        if not train_script.exists():
            missing.append(f"retrain: {train_script} not found")
        if not ledger.exists():
            missing.append(f"retrain: outcome_ledger.db not found")

    return caps, missing


def print_capability_report():
    """Print a human-readable capability report."""
    caps, missing = detect_capabilities()
    print("\n  CAPABILITY DETECTION")
    print("  " + "=" * 40)
    print(f"  Available: {', '.join(caps)}")
    if missing:
        print(f"\n  Not available ({len(missing)}):")
        for m in missing:
            print(f"    - {m}")
    print()

    # Show data file sizes
    print("  DATA FILES:")
    for label, path in [
        ("outcome_ledger.db", DATA_DIR / "outcome_ledger.db"),
        ("shapes.db", DATA_DIR / "shapes.db"),
        ("genome_registry.db", DATA_DIR / "genome_registry.db"),
        ("forwards.jsonl", FORWARDS_DIR / "forwards.jsonl"),
        ("bank operators", BANK_DIR),
    ]:
        if path.is_dir():
            count = len(list(path.glob("op_*.py"))) if path.exists() else 0
            print(f"    {label}: {count} files")
        elif path.exists():
            size_mb = path.stat().st_size / 1024 / 1024
            print(f"    {label}: {size_mb:.1f} MB")
        else:
            print(f"    {label}: NOT FOUND")
    print()
    return caps


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
        # mine_eye_bulk.py uses a positional subcommand interface:
        #   python tools/mine_eye_bulk.py sets 2 5 11
        args.extend(["sets", str(repo_set_id)])
    else:
        args.append("all")

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


# ── SYNTHESIZE: generate operators via bulk_synthesize or near_miss_sweep ──

def handle_synthesize(spec, job_id):
    """Generate new operators. Uses bulk_synthesize.py if API key available,
    falls back to near_miss_sweep.py (no API key needed)."""
    count = spec.get("count", 10) if spec else 10
    cluster = spec.get("cluster") if spec else None

    bank_before = len(list(BANK_DIR.glob("op_*.py"))) if BANK_DIR.exists() else 0

    # --- Path 1: bulk_synthesize.py (needs API key) ---
    bulk_script = INTERCEPTOR_DIR / "tools" / "bulk_synthesize.py"
    has_api_key = any(os.environ.get(k) for k in (
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "LIGHTNING_API_KEY"
    ))

    # Detect Ollama as local fallback (OpenAI-compatible at localhost:11434)
    has_ollama = False
    ollama_model = "qwen2.5-coder:7b"
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        has_ollama = True
    except Exception:
        pass

    sweep_script = INTERCEPTOR_DIR / "tools" / "near_miss_sweep.py"

    if bulk_script.exists() and (has_api_key or has_ollama):
        args = [sys.executable, str(bulk_script), "--count", str(count)]
        if cluster:
            args.extend(["--cluster", cluster])
        if not has_api_key and has_ollama:
            # Use local Ollama model (free, no API key needed)
            args.extend(["--ollama", ollama_model])
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=900,
            cwd=str(INTERCEPTOR_DIR),
        )
        print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
        if result.stderr:
            print(result.stderr[-500:])
        path = "bulk_synthesize" + ("_ollama" if not has_api_key else "")
    elif sweep_script.exists():
        # --- Path 2: near_miss_sweep.py (no API key, uses local bank + forwards) ---
        top = max(3, count // 2)
        args = [sys.executable, str(sweep_script), "--top", str(top), "--compile"]
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=600,
            cwd=str(INTERCEPTOR_DIR),
        )
        print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
        if result.stderr:
            print(result.stderr[-500:])
        path = "near_miss_sweep"
    else:
        raise FileNotFoundError(
            f"No synthesize path available: bulk_synthesize.py needs API key or Ollama, "
            f"near_miss_sweep.py not found in {INTERCEPTOR_DIR / 'tools'}"
        )

    bank_after = len(list(BANK_DIR.glob("op_*.py"))) if BANK_DIR.exists() else 0
    new_ops = bank_after - bank_before

    # Upload any newly created operator files (up to 50)
    files = []
    if new_ops > 0 and BANK_DIR.exists():
        all_ops = sorted(BANK_DIR.glob("op_*.py"), key=lambda p: p.stat().st_mtime, reverse=True)
        files = all_ops[:min(new_ops, 50)]

    return {
        "path": path,
        "exit_code": result.returncode,
        "bank_before": bank_before,
        "bank_after": bank_after,
        "new_operators": new_ops,
        "output_tail": result.stdout[-300:],
    }, files


# ── Handler Registry ──────────────────────────────────────────────

HANDLERS = {
    "compile": handle_compile,
    "mine": handle_mine,
    "retrain": handle_retrain,
    "crossindex": handle_crossindex,
    "coverage": handle_coverage,
    "synthesize": handle_synthesize,
}
