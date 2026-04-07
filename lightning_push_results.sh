#!/bin/bash
# ============================================
#  Push mining results to GitHub for pickup
# ============================================
set -e

HARVEST_DB="$HOME/.entient/v2/pretrain_harvest.db"
RESULTS_REPO="$HOME/entient-agents"
RESULTS_DIR="$RESULTS_REPO/mining_results"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
HOSTNAME=$(hostname)

if [ ! -f "$HARVEST_DB" ]; then
    echo "[X] No harvest DB found at $HARVEST_DB"
    echo "    Run mining first: cd ~/entient-interceptor && python tools/mine_eye_bulk.py all"
    exit 1
fi

# Get harvest stats
SIZE_MB=$(du -m "$HARVEST_DB" | cut -f1)
echo "[+] Harvest DB: ${SIZE_MB} MB"

# Count observations if sqlite3 available
if command -v sqlite3 &>/dev/null; then
    OBS_COUNT=$(sqlite3 "$HARVEST_DB" "SELECT COUNT(*) FROM observations" 2>/dev/null || echo "unknown")
    echo "[+] Observations: $OBS_COUNT"
fi

# Export as JSONL (smaller, mergeable)
echo "[*] Exporting observations to JSONL..."
EXPORT_FILE="$RESULTS_DIR/harvest_${HOSTNAME}_${TIMESTAMP}.jsonl.gz"
mkdir -p "$RESULTS_DIR"

python3 -c "
import sqlite3, json, gzip, os
db = os.path.expanduser('~/.entient/v2/pretrain_harvest.db')
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
out = gzip.open('$EXPORT_FILE', 'wt', encoding='utf-8')
count = 0
for row in conn.execute('SELECT * FROM observations'):
    out.write(json.dumps(dict(row)) + '\n')
    count += 1
out.close()
print(f'  Exported {count} observations')
"

EXPORT_SIZE_MB=$(du -m "$EXPORT_FILE" | cut -f1)
echo "[+] Export: ${EXPORT_SIZE_MB} MB (gzipped)"

# Commit and push
cd "$RESULTS_REPO"
git add mining_results/
git commit -m "Mining harvest from ${HOSTNAME} — ${TIMESTAMP}

Source: Lightning.ai
Observations: ${OBS_COUNT:-unknown}
Size: ${SIZE_MB} MB raw, ${EXPORT_SIZE_MB} MB compressed"

git push origin master || git push origin main

echo ""
echo "[OK] Results pushed to entient-agents/mining_results/"
echo "     Pull on home PC to merge into probe.db"
