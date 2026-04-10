"""Upload new bank operators to coordinator.
Diffs local bank against coordinator's known operators, uploads only new ones.
"""
import argparse
import os
import requests
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coordinator", default="http://100.101.178.111:8420")
    parser.add_argument("--bank", default=str(Path.home() / ".entient" / "bank"))
    args = parser.parse_args()

    bank = Path(args.bank)
    url = args.coordinator

    # Fetch remote operator list
    try:
        resp = requests.get(f"{url}/bootstrap/bank", timeout=15)
        resp.raise_for_status()
        remote = set(resp.json().get("operators", []))
    except Exception as e:
        print(f"Could not fetch remote bank list: {e}")
        return

    # Find local ops not on coordinator
    local_ops = list(bank.glob("op_*.py"))
    new_ops = [p for p in local_ops if p.name not in remote]

    if not new_ops:
        print(f"Nothing new to upload ({len(local_ops)} local, {len(remote)} remote).")
        return

    print(f"Uploading {len(new_ops)} new operators ({len(local_ops)} local, {len(remote)} remote)...")

    uploaded = 0
    failed = 0
    for op in new_ops:
        try:
            # Create a direct_upload job
            job_resp = requests.post(f"{url}/jobs/create", json={
                "job_type": "direct_upload", "spec": {}, "priority": 5
            }, timeout=10)
            job_resp.raise_for_status()
            job_id = job_resp.json()["job_id"]

            # Upload the file
            with open(op, "rb") as f:
                up = requests.post(f"{url}/results/upload",
                    data={"job_id": job_id, "job_type": "direct_upload"},
                    files={"file": (op.name, f)},
                    timeout=30)
            if up.status_code == 200:
                uploaded += 1
            else:
                print(f"  FAIL {op.name}: {up.status_code} {up.text[:100]}")
                failed += 1
        except Exception as e:
            print(f"  FAIL {op.name}: {e}")
            failed += 1

    print(f"Done: {uploaded} uploaded, {failed} failed.")

if __name__ == "__main__":
    main()
