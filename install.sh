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
echo "[1/6] Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

# Install Python packages
echo "[2/6] Installing Python packages..."
pip install requests pynacl cryptography cbor2 pyyaml -q

# Clone repos (all 3 needed for full capability)
echo "[3/6] Cloning repositories..."
mkdir -p repos

if [ ! -d "repos/entient" ]; then
    echo "      Cloning entient (core)..."
    git clone https://github.com/Entient/entient.git repos/entient
else
    echo "      entient already cloned, pulling latest..."
    cd repos/entient && git pull && cd ../..
fi

if [ ! -d "repos/entient-agents" ]; then
    echo "      Cloning entient-agents..."
    git clone https://github.com/Entient/entient-agents.git repos/entient-agents
else
    echo "      entient-agents already cloned, pulling latest..."
    cd repos/entient-agents && git pull && cd ../..
fi

if [ ! -d "repos/entient-interceptor" ]; then
    echo "      Cloning entient-interceptor..."
    git clone https://github.com/Entient/entient-interceptor.git repos/entient-interceptor
else
    echo "      entient-interceptor already cloned, pulling latest..."
    cd repos/entient-interceptor && git pull && cd ../..
fi

# Install repos in dependency order
echo "[4/6] Installing repo packages..."
echo "      Installing entient (core)..."
pip install -e repos/entient -q || echo "[!] entient install failed"
echo "      Installing entient-agents..."
pip install -e repos/entient-agents -q || echo "[!] entient-agents install failed"
echo "      Installing entient-interceptor..."
pip install -e repos/entient-interceptor -q || echo "[!] entient-interceptor install failed"

# Write config
echo "[5/6] Writing config..."
cat > config.json << EOF
{
  "coordinator_url": "$COORD_URL",
  "worker_name": "$WORKER_NAME",
  "capabilities": "auto",
  "poll_interval": 10,
  "heartbeat_interval": 60
}
EOF

# Create data dirs
echo "[6/6] Creating data directories..."
mkdir -p ~/.entient/bank
mkdir -p ~/.entient/v2
mkdir -p ~/.entient/weights
mkdir -p ~/.entient/forwards

# Check capabilities
echo ""
echo "  Checking what this machine can run..."
echo ""
python3 worker.py --check

echo ""
echo "  ============================================"
echo "   Install complete!"
echo ""
echo "   Coordinator: $COORD_URL"
echo "   Worker name: $WORKER_NAME"
echo ""
echo "   NEXT STEPS:"
echo "   1. Run: ./start.sh --bootstrap"
echo "      (Downloads DBs from coordinator)"
echo "   2. Then: ./start.sh"
echo "      (Starts the worker)"
echo "   3. For CROSSINDEX: copy shapes.db (5GB) via USB to"
echo "      ~/.entient/v2/shapes.db"
echo "  ============================================"
echo ""
