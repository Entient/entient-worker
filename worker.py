#!/usr/bin/env python3
"""Entient Remote Worker — claims and executes jobs from coordinator.

Usage:
    python worker.py                    # start with config.json (auto-detect caps)
    python worker.py --check            # check what this machine can run
    python worker.py --bootstrap        # download DBs from coordinator
    python worker.py --url http://IP:8420 --name my-pc   # override
"""
import json
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path

import requests

CONFIG_FILE = Path(__file__).parent / "config.json"
DATA_DIR = Path(os.path.expanduser("~/.entient/v2"))
BANK_DIR = Path(os.path.expanduser("~/.entient/bank"))
FORWARDS_DIR = Path(os.path.expanduser("~/.entient/forwards"))


def bootstrap_from_coordinator(coordinator_url):
    """Download database files from the coordinator to enable more capabilities."""
    url = coordinator_url.rstrip("/")
    print(f"Bootstrapping from {url}...")

    # Check what's available
    try:
        resp = requests.get(f"{url}/bootstrap", timeout=10)
        available = resp.json()
    except Exception as e:
        print(f"[!] Cannot reach coordinator: {e}")
        return

    print(f"  Coordinator has: {list(available.get('files', {}).keys())}")
    print(f"  Bank operators: {available.get('bank_operators', 0)}")

    # Download each file we don't have
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FORWARDS_DIR.mkdir(parents=True, exist_ok=True)

    targets = {
        "outcome_ledger.db": DATA_DIR / "outcome_ledger.db",
        "genome_registry.db": DATA_DIR / "genome_registry.db",
        "forwards.jsonl": FORWARDS_DIR / "forwards.jsonl",
        # shapes.db intentionally excluded — too large (5+ GB) for download
        # Use: python worker.py --bootstrap --include-shapes to override
    }

    for filename, dest in targets.items():
        if filename not in available.get("files", {}):
            print(f"  {filename}: not available on coordinator")
            continue
        info = available["files"][filename]
        if dest.exists():
            local_size = dest.stat().st_size
            remote_size = info["size_bytes"]
            if abs(local_size - remote_size) < 1024:  # within 1KB
                print(f"  {filename}: up to date ({info['size_mb']} MB)")
                continue
            print(f"  {filename}: local {local_size/1024/1024:.1f} MB vs remote {info['size_mb']} MB — updating")
        else:
            print(f"  {filename}: downloading ({info['size_mb']} MB)...")

        try:
            resp = requests.get(f"{url}/bootstrap/{filename}", timeout=300, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"  {filename}: OK ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
        except Exception as e:
            print(f"  {filename}: FAILED ({e})")

    # Download bank operators
    BANK_DIR.mkdir(parents=True, exist_ok=True)
    try:
        print(f"\n  Downloading bank operators...")
        resp = requests.get(f"{url}/bootstrap/bank.tar.gz", timeout=300, stream=True)
        if resp.status_code == 200:
            import tarfile, io
            buf = io.BytesIO(resp.content)
            with tarfile.open(fileobj=buf, mode="r:gz") as tar:
                tar.extractall(path=str(BANK_DIR))
            count = len(list(BANK_DIR.glob("op_*.py")))
            print(f"  bank: OK ({count} operators)")
        else:
            print(f"  bank: server returned {resp.status_code} (upgrade coordinator for bank sync)")
    except Exception as e:
        print(f"  bank: FAILED ({e})")

    # Note about shapes.db
    shapes = DATA_DIR / "shapes.db"
    if not shapes.exists():
        shapes_info = available.get("files", {}).get("shapes.db")
        if shapes_info:
            print(f"\n  NOTE: shapes.db ({shapes_info['size_mb']} MB) is too large for HTTP download.")
            print(f"  Copy it manually: scp coordinator:~/.entient/v2/shapes.db {shapes}")
            print(f"  Or use a USB drive. This unlocks the CROSSINDEX capability.")


def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


class Worker:
    def __init__(self, coordinator_url: str, name: str, capabilities: list):
        self.url = coordinator_url.rstrip("/")
        self.name = name
        self.capabilities = capabilities
        self.worker_id = None
        self.running = True
        self.current_job = None

    def register(self):
        """Register with the coordinator."""
        resp = requests.post(f"{self.url}/register", json={
            "worker_name": self.name,
            "hostname": socket.gethostname(),
            "capabilities": self.capabilities,
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        self.worker_id = data["worker_id"]
        print(f"[+] Registered as {self.worker_id} ({self.name})")

    def heartbeat(self):
        """Send heartbeat to coordinator."""
        try:
            resp = requests.post(f"{self.url}/heartbeat", json={
                "worker_id": self.worker_id,
                "state": "busy" if self.current_job else "active",
            }, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("pending_jobs", 0)
        except Exception as e:
            print(f"[!] Heartbeat failed: {e}")
        return 0

    def claim_job(self):
        """Try to claim a pending job."""
        try:
            resp = requests.post(f"{self.url}/jobs/claim", json={
                "worker_id": self.worker_id,
                "capabilities": self.capabilities,
            }, timeout=10)
            if resp.status_code == 204:
                return None
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"[!] Claim failed: {e}")
        return None

    def complete_job(self, job_id: str, result: dict = None, error: str = None):
        """Report job completion."""
        try:
            requests.post(f"{self.url}/jobs/{job_id}/complete", json={
                "result": result or {},
                "error": error,
            }, timeout=10)
        except Exception as e:
            print(f"[!] Complete failed: {e}")

    def upload_file(self, job_id: str, job_type: str, filepath: Path):
        """Upload a result file to the coordinator."""
        try:
            with open(filepath, "rb") as f:
                resp = requests.post(f"{self.url}/results/upload",
                    data={"job_id": job_id, "job_type": job_type},
                    files={"file": (filepath.name, f)},
                    timeout=120)
                if resp.status_code == 200:
                    data = resp.json()
                    merged = data.get("merged", False)
                    print(f"  [UP] Uploaded {filepath.name}" + (" (merged)" if merged else ""))
        except Exception as e:
            print(f"  [!] Upload failed for {filepath.name}: {e}")

    def execute_job(self, job: dict):
        """Dispatch job to the right handler."""
        job_id = job["job_id"]
        job_type = job["job_type"]
        spec = job.get("spec", {})
        self.current_job = job_id

        print(f"\n[>] Executing {job_type} job {job_id}")
        start = time.time()

        try:
            from job_handlers import HANDLERS
            handler = HANDLERS.get(job_type)
            if not handler:
                raise ValueError(f"Unknown job type: {job_type}")

            result, files = handler(spec, job_id)
            elapsed = time.time() - start
            result["elapsed_s"] = round(elapsed, 1)

            # Upload any result files
            for fp in files:
                self.upload_file(job_id, job_type, fp)

            self.complete_job(job_id, result=result)
            print(f"[OK] Job {job_id} done in {elapsed:.1f}s")

        except Exception as e:
            elapsed = time.time() - start
            print(f"[FAIL] Job {job_id} failed after {elapsed:.1f}s: {e}")
            self.complete_job(job_id, error=str(e))

        self.current_job = None

    def run(self):
        """Main worker loop."""
        print(f"Connecting to coordinator at {self.url}")
        print(f"Capabilities: {self.capabilities}")
        print(f"Press Ctrl+C to stop.\n")

        # Register with retry
        for attempt in range(5):
            try:
                self.register()
                break
            except Exception as e:
                wait = min(10 * (attempt + 1), 60)
                print(f"[!] Registration failed: {e}. Retry in {wait}s...")
                time.sleep(wait)
        else:
            print("[X] Could not register. Check coordinator URL.")
            return

        # Heartbeat thread
        def heartbeat_loop():
            while self.running:
                self.heartbeat()
                time.sleep(60)

        hb = threading.Thread(target=heartbeat_loop, daemon=True)
        hb.start()

        # Main poll loop
        poll_interval = 10
        idle_count = 0
        while self.running:
            job = self.claim_job()
            if job:
                idle_count = 0
                self.execute_job(job)
            else:
                idle_count += 1
                # Back off when idle: 10s → 20s → 30s (max)
                wait = min(poll_interval + (idle_count * 5), 30)
                if idle_count % 6 == 1:  # Log every ~minute
                    print(f"[~] Idle, polling every {wait}s...")
                time.sleep(wait)

        print("[x] Worker stopped.")

    def stop(self):
        self.running = False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Entient Remote Worker")
    parser.add_argument("--url", help="Coordinator URL")
    parser.add_argument("--name", help="Worker name")
    parser.add_argument("--caps", nargs="+", default=None,
                        help="Override capabilities (default: auto-detect)")
    parser.add_argument("--check", action="store_true",
                        help="Check capabilities and exit (no connection)")
    parser.add_argument("--bootstrap", action="store_true",
                        help="Download DB files from coordinator to unlock more capabilities")
    args = parser.parse_args()

    # Auto-detect capabilities
    from job_handlers import detect_capabilities, print_capability_report

    if args.check:
        print_capability_report()
        return

    config = load_config()

    if args.bootstrap:
        url = args.url or config.get("coordinator_url", "http://localhost:8420")
        bootstrap_from_coordinator(url)
        print("\nRe-checking capabilities after bootstrap:")
        print_capability_report()
        return


    url = args.url or config.get("coordinator_url", "http://localhost:8420")
    name = args.name or config.get("worker_name", socket.gethostname())

    if args.caps:
        caps = args.caps
    else:
        caps, missing = detect_capabilities()
        print(f"Auto-detected capabilities: {caps}")
        if missing:
            print(f"  ({len(missing)} job types unavailable — run --check for details)")

    worker = Worker(url, name, caps)

    def shutdown(sig, frame):
        print("\n[x] Shutting down...")
        worker.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    worker.run()


if __name__ == "__main__":
    main()
