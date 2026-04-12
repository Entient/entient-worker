#!/usr/bin/env python3
"""pipeline_health.py — Entient pipeline health checker for BrockPC.

Usage:
    python pipeline_health.py          # print full report
    python pipeline_health.py --fix    # print + auto-fix what it can
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────
HARVEST_DB      = Path("E:/entient/repos/pretrain_harvest.db")
BANK_DIR        = Path(os.path.expanduser("~/.entient/bank"))
WORKER_RESULTS  = Path(os.path.expanduser("~/.entient/v2/worker_results"))
STATE_FILE      = Path(os.path.expanduser("~/.entient/v2/health_state.json"))
AGENT_DIR       = Path("C:/entient-worker/repos/entient-agents")
COMPILER_SCRIPT = AGENT_DIR / "tools" / "operator_compiler.py"
PYTHON          = Path("C:/entient-worker/.venv/Scripts/python.exe")

HARVEST_DB_WARN_GB  = 2.0
HARVEST_AGE_WARN_H  = 4.0
WORKER_RESULTS_WARN_GB = 2.0
DISK_CRIT_GB        = 10.0
GROWTH_STALE_H      = 4.0
STATE_HISTORY_MAX   = 24


# ── Helpers ───────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

def now_dt() -> datetime.datetime:
    return datetime.datetime.now()

def parse_iso(s: str) -> datetime.datetime:
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")

def dir_size_gb(p: Path) -> float:
    if not p.exists():
        return 0.0
    total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return round(total / 1_073_741_824, 2)

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "last_run": now_iso(),
        "bank_count_history": [],
        "harvest_db_size_history": [],
    }

def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

def trim_history(lst: list, max_entries: int) -> list:
    return lst[-max_entries:] if len(lst) > max_entries else lst

def is_process_running(name_fragment: str) -> bool:
    """Check if a process whose command line contains name_fragment is running."""
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        # tasklist /FO CSV gives process names only; check wmic for command lines
        wmic = subprocess.run(
            ["wmic", "process", "get", "commandline", "/format:csv"],
            capture_output=True, text=True, timeout=10,
        )
        return name_fragment.lower() in wmic.stdout.lower()
    except Exception:
        return False

def get_disk_free_gb(drive: str = "C") -> float:
    try:
        usage = shutil.disk_usage(f"{drive}:/")
        return round(usage.free / 1_073_741_824, 1)
    except Exception:
        return -1.0


# ── Checks ────────────────────────────────────────────────────────

def check_harvest_db_size(state: dict) -> tuple:
    """Returns (label, value_str, status, gb)."""
    if not HARVEST_DB.exists():
        return "Harvest DB", "missing", "WARN", 0.0
    gb = round(HARVEST_DB.stat().st_size / 1_073_741_824, 2)
    state.setdefault("harvest_db_size_history", []).append({"ts": now_iso(), "gb": gb})
    state["harvest_db_size_history"] = trim_history(state["harvest_db_size_history"], STATE_HISTORY_MAX)
    if gb > HARVEST_DB_WARN_GB:
        return "Harvest DB", f"{gb} GB", "CRIT", gb
    return "Harvest DB", f"{gb} GB", "OK", gb

def check_harvest_db_age() -> tuple:
    if not HARVEST_DB.exists():
        return "Harvest DB age", "missing", "WARN"
    age_h = round((now_dt() - datetime.datetime.fromtimestamp(HARVEST_DB.stat().st_mtime)).total_seconds() / 3600, 1)
    if age_h > HARVEST_AGE_WARN_H:
        return "Harvest DB age", f"{age_h}h", "WARN"
    return "Harvest DB age", f"{age_h}h", "OK"

def check_bank_growth(state: dict) -> tuple:
    if not BANK_DIR.exists():
        return "Bank growth", "bank dir missing", "WARN"
    count = len(list(BANK_DIR.glob("op_*.py")))
    history = state.setdefault("bank_count_history", [])
    history.append({"ts": now_iso(), "count": count})
    state["bank_count_history"] = trim_history(history, STATE_HISTORY_MAX)

    # Find entry ~1h ago
    one_h_ago = now_dt() - datetime.timedelta(hours=1)
    older = [e for e in history[:-1] if parse_iso(e["ts"]) <= one_h_ago]
    if older:
        ref = older[-1]
        delta = count - ref["count"]
        delta_str = f"+{delta}/h" if delta >= 0 else f"{delta}/h"
        # Check for stale growth during business hours (6am-10pm)
        hour = now_dt().hour
        if delta == 0 and 6 <= hour < 22:
            stale_since_h = (now_dt() - parse_iso(older[-1]["ts"])).total_seconds() / 3600
            if stale_since_h >= GROWTH_STALE_H:
                return "Bank growth", delta_str, "WARN"
        return "Bank growth", delta_str, "OK"
    return "Bank growth", f"{count} ops (no history yet)", "OK"

def check_worker_results() -> tuple:
    gb = dir_size_gb(WORKER_RESULTS)
    if gb > WORKER_RESULTS_WARN_GB:
        return "worker_results", f"{gb} GB", "CRIT", gb
    return "worker_results", f"{gb} GB", "OK", gb

def check_loop(name: str, fragment: str) -> tuple:
    running = is_process_running(fragment)
    status = "running" if running else "DEAD"
    flag = "OK" if running else "CRIT"
    return name, status, flag

def check_disk() -> tuple:
    gb = get_disk_free_gb("C")
    if gb < 0:
        return "Disk (C:)", "unknown", "WARN"
    if gb < DISK_CRIT_GB:
        return "Disk (C:)", f"{gb} GB", "CRIT"
    return "Disk (C:)", f"{gb} GB", "OK"


# ── Fix actions ───────────────────────────────────────────────────

def fix_worker_results():
    """Delete oldest worker_results dirs until total is under 2 GB."""
    print("  [fix] Cleaning worker_results...")
    if not WORKER_RESULTS.exists():
        return
    dirs = sorted(WORKER_RESULTS.iterdir(), key=lambda d: d.stat().st_mtime)
    while dir_size_gb(WORKER_RESULTS) > WORKER_RESULTS_WARN_GB and len(dirs) > 1:
        d = dirs.pop(0)
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            print(f"  [fix] Removed {d.name}")
    print(f"  [fix] worker_results now {dir_size_gb(WORKER_RESULTS)} GB")

def fix_harvest_db():
    """Run OperatorCompiler to drain the harvest DB."""
    print("  [fix] Running OperatorCompiler to drain harvest DB...")
    py = str(PYTHON) if PYTHON.exists() else sys.executable
    if not COMPILER_SCRIPT.exists():
        print(f"  [fix] compiler script not found: {COMPILER_SCRIPT}")
        return
    r = subprocess.run(
        [py, str(COMPILER_SCRIPT), "--db", str(HARVEST_DB), "--promote", "--top", "200"],
        timeout=300, cwd=str(AGENT_DIR),
    )
    print(f"  [fix] OperatorCompiler exit={r.returncode}")

def print_restart_hint(loop_name: str, script: str):
    print(f"  [fix] {loop_name} is dead. To restart:")
    print(f"    powershell -ExecutionPolicy Bypass -File C:\\entient-worker\\{script}")


# ── Report ────────────────────────────────────────────────────────

def fmt_row(label: str, value: str, flag: str) -> str:
    pad = 16
    flag_str = f"[{flag}]"
    return f"  {label:<{pad}} {value:<12}  {flag_str}"

def main():
    parser = argparse.ArgumentParser(description="Entient pipeline health checker")
    parser.add_argument("--fix", action="store_true", help="Auto-fix issues where possible")
    args = parser.parse_args()

    state = load_state()

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"=== Entient Pipeline Health [{ts}] ===")

    results = []
    any_crit = False

    # 1. Harvest DB size
    label, val, flag, db_gb = check_harvest_db_size(state)
    results.append((label, val, flag))
    if flag == "CRIT":
        any_crit = True

    # 2. Harvest DB age
    label, val, flag = check_harvest_db_age()
    results.append((label, val, flag))
    if flag == "CRIT":
        any_crit = True

    # 3. Bank growth
    label, val, flag = check_bank_growth(state)
    results.append((label, val, flag))
    if flag == "CRIT":
        any_crit = True

    # 4. worker_results size
    label, val, flag, wr_gb = check_worker_results()
    results.append((label, val, flag))
    if flag == "CRIT":
        any_crit = True

    # 5. Loop liveness
    mine_label, mine_val, mine_flag = check_loop("Mine loop", "mine_loop")
    results.append((mine_label, mine_val, mine_flag))
    if mine_flag == "CRIT":
        any_crit = True

    synth_label, synth_val, synth_flag = check_loop("Synth loop", "synth_loop")
    results.append((synth_label, synth_val, synth_flag))
    if synth_flag == "CRIT":
        any_crit = True

    # 6. Disk headroom
    label, val, flag = check_disk()
    results.append((label, val, flag))
    if flag == "CRIT":
        any_crit = True

    for row in results:
        print(fmt_row(*row))

    state["last_run"] = now_iso()
    save_state(state)

    if args.fix:
        print()
        print("=== Fix pass ===")
        if db_gb > HARVEST_DB_WARN_GB:
            fix_harvest_db()
        if wr_gb > WORKER_RESULTS_WARN_GB:
            fix_worker_results()
        if mine_flag == "CRIT":
            print_restart_hint("Mine loop", "mine_loop.ps1")
        if synth_flag == "CRIT":
            print_restart_hint("Synth loop", "synth_loop.ps1")
        if not (db_gb > HARVEST_DB_WARN_GB or wr_gb > WORKER_RESULTS_WARN_GB
                or mine_flag == "CRIT" or synth_flag == "CRIT"):
            print("  Nothing to fix.")

    sys.exit(1 if any_crit else 0)


if __name__ == "__main__":
    main()
