"""Pull new operators from coordinator bank down to local bank.
Only downloads ops not already present locally.
"""
import argparse
import requests
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coordinator", default="http://100.101.178.111:8420")
    parser.add_argument("--bank", default=str(Path.home() / ".entient" / "bank"))
    args = parser.parse_args()

    bank = Path(args.bank)
    bank.mkdir(parents=True, exist_ok=True)
    url = args.coordinator

    # Fetch remote operator list
    try:
        resp = requests.get(f"{url}/bootstrap/bank", timeout=15)
        resp.raise_for_status()
        remote_ops = resp.json().get("operators", [])
    except Exception as e:
        print(f"Could not fetch remote bank list: {e}")
        return

    local = set(p.name for p in bank.glob("op_*.py"))
    to_download = [name for name in remote_ops if name not in local]

    if not to_download:
        print(f"Already up to date ({len(local)} local, {len(remote_ops)} remote).")
        return

    print(f"Downloading {len(to_download)} new operators ({len(local)} local, {len(remote_ops)} remote)...")

    downloaded = 0
    failed = 0
    for name in to_download:
        try:
            r = requests.get(f"{url}/bootstrap/bank/{name}", timeout=30)
            if r.status_code == 200:
                (bank / name).write_bytes(r.content)
                downloaded += 1
            else:
                print(f"  FAIL {name}: {r.status_code}")
                failed += 1
        except Exception as e:
            print(f"  FAIL {name}: {e}")
            failed += 1

    print(f"Done: {downloaded} downloaded, {failed} failed.")

if __name__ == "__main__":
    main()
