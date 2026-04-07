#!/bin/bash
# ============================================
#  ENTIENT Mining Worker — Lightning.ai Setup
#  Run this once on a new Lightning.ai studio
# ============================================
set -e

echo ""
echo "  ============================================"
echo "   ENTIENT Mining Worker — Lightning.ai"
echo "  ============================================"
echo ""

# ── 1. Clone repos ──────────────────────────────────────────────
echo "[1/4] Cloning repositories..."
cd ~

if [ ! -d "entient" ]; then
    git clone https://github.com/Entient/entient.git
else
    echo "  entient already cloned, pulling..."
    cd entient && git pull && cd ~
fi

if [ ! -d "entient-agents" ]; then
    git clone https://github.com/Entient/entient-agents.git
else
    echo "  entient-agents already cloned, pulling..."
    cd entient-agents && git pull && cd ~
fi

if [ ! -d "entient-interceptor" ]; then
    git clone https://github.com/Entient/entient-interceptor.git
else
    echo "  entient-interceptor already cloned, pulling..."
    cd entient-interceptor && git pull && cd ~
fi

# ── 2. Install packages ────────────────────────────────────────
echo "[2/4] Installing packages..."
pip install -e ~/entient/ -q 2>/dev/null
pip install -e ~/entient-agents/ -q 2>/dev/null
pip install -e ~/entient-interceptor/ -q 2>/dev/null

# ── 3. Create data dirs ────────────────────────────────────────
echo "[3/4] Creating data directories..."
mkdir -p ~/.entient/v2 ~/.entient/bank ~/.entient/forwards

# ── 4. Verify ───────────────────────────────────────────────────
echo "[4/4] Verifying installation..."
python -c "from entient_interceptor.eye import Eye; print('  Eye: OK')" 2>/dev/null || echo "  Eye: FAILED"
python -c "from entient_agent.probe.engine import ProbeEngine; print('  ProbeEngine: OK')" 2>/dev/null || echo "  ProbeEngine: FAILED"

echo ""
echo "  ============================================"
echo "   Setup complete!"
echo ""
echo "   To start mining:"
echo "     cd ~/entient-interceptor"
echo "     python tools/mine_eye_bulk.py list        # see available sets"
echo "     python tools/mine_eye_bulk.py all         # mine everything"
echo "     python tools/mine_eye_bulk.py sets 1 2 3  # mine specific sets"
echo ""
echo "   Results go to: ~/.entient/v2/pretrain_harvest.db"
echo ""
echo "   When done, push results to GitHub:"
echo "     bash ~/lightning_push_results.sh"
echo "  ============================================"
echo ""
