#!/bin/bash
set -e

echo ""
echo "  ============================================"
echo "   ENTIENT Remote Worker — One-Click Install"
echo "  ============================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[X] Python 3 not found. Install: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi
PYVER=$(python3 --version)
echo "[OK] $PYVER found"

# Check Git
if ! command -v git &> /dev/null; then
    echo "[X] Git not found. Install: sudo apt install git"
    exit 1
fi
echo "[OK] Git found"

# Get coordinator URL
echo ""
read -p "Coordinator URL (e.g. http://192.168.1.100:8420): " COORD_URL
COORD_URL=${COORD_URL:-http://localhost:8420}

# Get worker name
read -p "Worker name (e.g. gaming-pc): " WORKER_NAME
WORKER_NAME=${WORKER_NAME:-$(hostname)}

# Create venv
echo ""
echo "[1/5] Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

# Install requests
echo "[2/5] Installing dependencies..."
pip install requests -q

# Clone repos
echo "[3/5] Cloning repositories..."
mkdir -p repos

if [ ! -d "repos/entient-interceptor" ]; then
    git clone https://github.com/Entient/entient-interceptor.git repos/entient-interceptor
else
    echo "      entient-interceptor already cloned, pulling latest..."
    cd repos/entient-interceptor && git pull && cd ../..
fi

if [ ! -d "repos/entient-agents" ]; then
    git clone https://github.com/Entient/entient-agents.git repos/entient-agents
else
    echo "      entient-agents already cloned, pulling latest..."
    cd repos/entient-agents && git pull && cd ../..
fi

# Install repo deps
echo "[4/5] Installing repo dependencies..."
pip install -e repos/entient-agents -q 2>/dev/null || true
pip install -e repos/entient-interceptor -q 2>/dev/null || true

# Write config
echo "[5/5] Writing config..."
cat > config.json << EOF
{
  "coordinator_url": "$COORD_URL",
  "worker_name": "$WORKER_NAME",
  "capabilities": ["compile", "mine", "retrain", "crossindex", "coverage"],
  "poll_interval": 10,
  "heartbeat_interval": 60
}
EOF

# Create bank dir
mkdir -p ~/.entient/bank

echo ""
echo "  ============================================"
echo "   Install complete!"
echo ""
echo "   Coordinator: $COORD_URL"
echo "   Worker name: $WORKER_NAME"
echo ""
echo "   To start: ./start.sh"
echo "  ============================================"
echo ""
