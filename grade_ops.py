"""
grade_ops.py — Operator quality tier pipeline for BrockPC.

Scans the bank for shallow Qwen-generated operators, scores them 0-100 for
shallowness, optionally queues high-scoring (low-quality) ones to coordinator
for Haiku rewrite.

Usage:
  python grade_ops.py                         # dry run, top 5
  python grade_ops.py --report                # summary only, no queue
  python grade_ops.py --queue                 # POST jobs to coordinator
  python grade_ops.py --queue --top 10        # queue up to 10 per run
  python grade_ops.py --threshold 40          # only queue if score >= 40
  python grade_ops.py --coordinator http://...  # override coordinator URL
"""

import argparse
import ast
import json
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Defaults ────────────────────────────────────────────────────────────────

BANK_DIR        = Path(r"C:\Users\Brock\.entient\bank")
LEDGER_PATH     = BANK_DIR / "_polish_ledger.json"
MISS_CLUSTERS   = Path(r"C:\entient-worker\repos\entient-interceptor\eval\miss_clusters.json")
DEFAULT_COORDINATOR = "http://100.101.178.111:8420"
DEFAULT_THRESHOLD   = 30
DEFAULT_TOP         = 5
QUEUED_STALE_HOURS  = 24


# ── Ledger helpers ───────────────────────────────────────────────────────────

def load_ledger() -> dict:
    if LEDGER_PATH.exists():
        try:
            return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_ledger(ledger: dict) -> None:
    LEDGER_PATH.write_text(json.dumps(ledger, indent=2), encoding="utf-8")


def ledger_entry_stale(entry: dict) -> bool:
    """Return True if a 'queued' entry is older than QUEUED_STALE_HOURS."""
    queued_at_str = entry.get("queued_at")
    if not queued_at_str:
        return True
    try:
        queued_at = datetime.fromisoformat(queued_at_str)
        # Make aware if naive
        if queued_at.tzinfo is None:
            queued_at = queued_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - queued_at).total_seconds() > QUEUED_STALE_HOURS * 3600
    except Exception:
        return True


# ── Miss cluster helpers ─────────────────────────────────────────────────────

def load_miss_clusters() -> list:
    if not MISS_CLUSTERS.exists():
        return []
    try:
        data = json.loads(MISS_CLUSTERS.read_text(encoding="utf-8"))
        # Support both list and dict-of-lists formats
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Flatten all cluster lists
            result = []
            for v in data.values():
                if isinstance(v, list):
                    result.extend(v)
            return result
    except Exception:
        return []
    return []


def infer_cluster(op_keywords: list, clusters: list) -> str:
    """
    Return the best-matching gap_channel from miss_clusters by keyword overlap.
    Requires at least 2 overlapping keywords. Returns 'unknown' if none qualify.
    """
    if not op_keywords or not clusters:
        return "unknown"

    op_kw_set = {k.lower() for k in op_keywords}
    best_channel = "unknown"
    best_overlap = 0

    for cluster in clusters:
        channel = cluster.get("gap_channel", cluster.get("channel", "unknown"))
        cluster_kws = cluster.get("keywords", cluster.get("top_keywords", []))
        cluster_kw_set = {k.lower() for k in cluster_kws}
        overlap = len(op_kw_set & cluster_kw_set)
        if overlap >= 2 and overlap > best_overlap:
            best_overlap = overlap
            best_channel = channel

    return best_channel


# ── Operator parsing ─────────────────────────────────────────────────────────

def extract_template_source(source: str) -> str:
    """
    Extract the string value of the `template=` assignment from op source.
    Uses regex only (no exec/eval).
    Returns the raw string content (unescaped), or '' if not found.
    """
    # Match template="""...""" or template='''...''' (multiline)
    for quote in ('"""', "'''"):
        pattern = r'template\s*=\s*' + re.escape(quote) + r'(.*?)' + re.escape(quote)
        m = re.search(pattern, source, re.DOTALL)
        if m:
            return m.group(1)

    # Match template="..." or template='...' (single-line, possibly with escapes)
    m = re.search(r'template\s*=\s*(["\'])((?:\\.|[^\\])*?)\1', source, re.DOTALL)
    if m:
        raw = m.group(2)
        # Unescape common sequences
        raw = raw.replace(r'\n', '\n').replace(r'\t', '\t').replace(r'\\', '\\')
        return raw

    return ""


def parse_op_metadata(source: str) -> dict:
    """
    Parse lightweight metadata from an operator source file using regex.
    Returns a dict with keys: name, cluster, params, param_extractors,
    structural_idiom, template_source, keywords.
    """
    meta = {
        "name": "",
        "cluster": "unknown",
        "params": {},
        "param_extractors": [],
        "structural_idiom": "",
        "template_source": "",
        "keywords": [],
    }

    # name=
    m = re.search(r'\bname\s*=\s*["\']([^"\']+)["\']', source)
    if m:
        meta["name"] = m.group(1)

    # cluster=
    m = re.search(r'\bcluster\s*=\s*["\']([^"\']+)["\']', source)
    if m:
        meta["cluster"] = m.group(1)

    # structural_idiom=
    m = re.search(r'\bstructural_idiom\s*=\s*["\']([^"\']+)["\']', source)
    if m:
        meta["structural_idiom"] = m.group(1)

    # keywords= list
    m = re.search(r'\bkeywords\s*=\s*\[([^\]]*)\]', source, re.DOTALL)
    if m:
        kws = re.findall(r'["\']([^"\']+)["\']', m.group(1))
        meta["keywords"] = kws

    # params= dict (simple single-level)
    m = re.search(r'\bparams\s*=\s*\{([^}]*)\}', source, re.DOTALL)
    if m:
        pairs = re.findall(r'["\']([^"\']+)["\']\s*:\s*["\']([^"\']*)["\']', m.group(1))
        meta["params"] = dict(pairs)

    # param_extractors= list of strings/regexes
    m = re.search(r'\bparam_extractors\s*=\s*\[([^\]]*)\]', source, re.DOTALL)
    if m:
        extractors = re.findall(r'["\']([^"\']+)["\']', m.group(1))
        meta["param_extractors"] = extractors

    # template
    meta["template_source"] = extract_template_source(source)

    return meta


# ── Scoring ──────────────────────────────────────────────────────────────────

def score_shallowness(meta: dict) -> tuple[int, list[str]]:
    """
    Score an operator 0-100 for shallowness (higher = shallower = worse quality).
    Returns (score, list_of_reasons).
    """
    score = 0
    reasons = []

    tmpl = meta.get("template_source", "")
    tmpl_stripped = tmpl.strip()
    tmpl_lines = [l for l in tmpl_stripped.splitlines() if l.strip()]

    # +40: template contains `# Your code here`
    if "# Your code here" in tmpl:
        score += 40
        reasons.append("+40: contains '# Your code here'")

    # +35: template contains `return {param}` as only logic
    #   Defined as: the only non-blank line (aside from def/return) is `return {something}`
    non_blank = [l.strip() for l in tmpl_stripped.splitlines() if l.strip()]
    return_only = (
        len(non_blank) == 1 and re.match(r'^return\s+\{', non_blank[0])
    ) or (
        len(non_blank) == 2
        and re.match(r'^def\s+', non_blank[0])
        and re.match(r'^return\s+\{', non_blank[1])
    )
    if return_only:
        score += 35
        reasons.append("+35: only logic is `return {param}`")

    # +30: template body is `pass` or empty
    if tmpl_stripped in ("", "pass") or all(l.strip() in ("", "pass") for l in tmpl_stripped.splitlines()):
        score += 30
        reasons.append("+30: template body is pass or empty")

    # +20: template has < 4 lines
    if len(tmpl_lines) < 4:
        score += 20
        reasons.append(f"+20: template has {len(tmpl_lines)} lines (< 4)")

    # +15: cluster == 'unknown'
    if meta.get("cluster", "unknown") == "unknown":
        score += 15
        reasons.append("+15: cluster is 'unknown'")

    # +15: params has generic key "param" with value "value" or "default"
    params = meta.get("params", {})
    if "param" in params and params["param"] in ("value", "default"):
        score += 15
        reasons.append(f"+15: generic param key 'param' = '{params['param']}'")

    # +10: no control flow in template
    if tmpl and not re.search(r'\b(if|for|while|try)\b', tmpl):
        score += 10
        reasons.append("+10: no control flow in template")

    # +10: structural_idiom == 'direct-return' AND template < 5 lines
    if meta.get("structural_idiom") == "direct-return" and len(tmpl_lines) < 5:
        score += 10
        reasons.append("+10: structural_idiom=direct-return and < 5 lines")

    # +5: param_extractors has generic `(.+?)` regex
    extractors = meta.get("param_extractors", [])
    if any(re.search(r'\(\.\+\?\)', ex) for ex in extractors):
        score += 5
        reasons.append("+5: param_extractor has generic (.+?) regex")

    return min(score, 100), reasons


# ── Coordinator POST ──────────────────────────────────────────────────────────

def post_job(coordinator_url: str, op_name: str, cluster: str) -> bool:
    """POST a polish job to coordinator. Returns True on success."""
    url = coordinator_url.rstrip("/") + "/jobs/create"
    payload = {
        "job_type": "synthesize",
        "spec": {
            "model": "haiku",
            "cluster": cluster,
            "quality": True,
            "count": 1,
            "polish_target": op_name,
        },
        "priority": 3,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            print(f"    POST {url} → {resp.status} {body[:120]}")
            return resp.status < 300
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"    POST {url} → HTTP {e.code}: {body[:120]}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"    POST {url} → error: {exc}", file=sys.stderr)
        return False


# ── Main scan ─────────────────────────────────────────────────────────────────

def scan_bank(bank_dir: Path) -> list[Path]:
    """Return all op_*.py files in bank dir."""
    if not bank_dir.exists():
        return []
    return sorted(bank_dir.glob("op_*.py"))


def run(args: argparse.Namespace) -> None:
    ledger = load_ledger()
    clusters = load_miss_clusters()
    now_iso = datetime.now(timezone.utc).isoformat()

    op_files = scan_bank(BANK_DIR)
    if not op_files:
        print(f"No op_*.py files found in {BANK_DIR}")
        return

    print(f"Bank: {len(op_files)} ops | Miss clusters: {len(clusters)}")

    results = []

    for op_path in op_files:
        op_name = op_path.stem  # e.g. op_summarize_text

        # Check ledger
        entry = ledger.get(op_name, {})
        if entry.get("status") == "queued" and not ledger_entry_stale(entry):
            # Already queued recently, skip unless --report
            if not args.report:
                continue

        try:
            source = op_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            print(f"  WARN: cannot read {op_path.name}: {exc}", file=sys.stderr)
            continue

        meta = parse_op_metadata(source)
        if not meta["name"]:
            meta["name"] = op_name

        score, reasons = score_shallowness(meta)

        # Infer cluster from miss clusters if unknown or default
        inferred_cluster = meta["cluster"]
        if inferred_cluster in ("unknown", "", None):
            inferred_cluster = infer_cluster(meta["keywords"], clusters)

        results.append({
            "op_name":          op_name,
            "op_path":          op_path,
            "score":            score,
            "reasons":          reasons,
            "cluster":          inferred_cluster,
            "ledger_entry":     entry,
            "meta":             meta,
        })

    # Sort descending by score
    results.sort(key=lambda r: r["score"], reverse=True)

    # ── Report ─────────────────────────────────────────────────────────────
    above_threshold = [r for r in results if r["score"] >= args.threshold]
    below_threshold = [r for r in results if r["score"] < args.threshold]

    print(f"\n=== Grade Report (threshold={args.threshold}) ===")
    print(f"  Shallow (>= threshold): {len(above_threshold)}")
    print(f"  OK     (<  threshold): {len(below_threshold)}")

    if args.report:
        print("\nTop shallow ops:")
        for r in above_threshold[:20]:
            print(f"  [{r['score']:3d}] {r['op_name']}  cluster={r['cluster']}")
            for reason in r["reasons"]:
                print(f"         {reason}")
        return

    # ── Mark done if previously queued but now below threshold ─────────────
    for r in below_threshold:
        entry = ledger.get(r["op_name"], {})
        if entry.get("status") in ("queued", "pending"):
            ledger[r["op_name"]] = {
                "status":    "done",
                "score":     r["score"],
                "cluster":   r["cluster"],
                "updated_at": now_iso,
            }
            print(f"  DONE: {r['op_name']} re-scored {r['score']} < threshold, marking done")

    # ── Queue top N above threshold ────────────────────────────────────────
    candidates = above_threshold[:args.top]

    queued_count = 0
    for r in candidates:
        op_name = r["op_name"]
        score   = r["score"]
        cluster = r["cluster"]

        print(f"\n  [{score:3d}] {op_name}  cluster={cluster}")
        for reason in r["reasons"]:
            print(f"       {reason}")

        if args.queue:
            success = post_job(args.coordinator, op_name, cluster)
            if success:
                ledger[op_name] = {
                    "status":     "queued",
                    "score":      score,
                    "cluster":    cluster,
                    "queued_at":  now_iso,
                }
                queued_count += 1
                print(f"    Queued: {op_name}")
            else:
                print(f"    FAILED to queue: {op_name}", file=sys.stderr)
        else:
            print(f"    (dry run — pass --queue to POST)")

    if args.queue:
        print(f"\nQueued {queued_count}/{len(candidates)} ops to {args.coordinator}")

    save_ledger(ledger)
    print(f"Ledger saved to {LEDGER_PATH}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Grade bank operators for shallowness and queue polish jobs."
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="POST polish jobs to coordinator for shallow ops",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        metavar="N",
        help=f"Max ops to queue per run (default: {DEFAULT_TOP})",
    )
    parser.add_argument(
        "--coordinator",
        type=str,
        default=DEFAULT_COORDINATOR,
        help=f"Coordinator base URL (default: {DEFAULT_COORDINATOR})",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help=f"Shallowness score threshold to queue (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Print summary report only, do not queue or mutate ledger",
    )

    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
