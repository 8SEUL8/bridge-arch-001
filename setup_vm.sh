#!/bin/bash
# ═══════════════════════════════════════════════════
# Bridge Arch 001 r2.1 — VM Setup Script
# Run this on your DigitalOcean Droplet
# ═══════════════════════════════════════════════════

echo "🐾 Bridge Arch 001 r2.1 — Setting up..."

# 1. Update system
apt update && apt upgrade -y

# 2. Python 3 should be pre-installed on Ubuntu 24.04
python3 --version

# 3. Create project directory
mkdir -p /root/bridge-arch
cd /root/bridge-arch

# 4. Create directory structure
mkdir -p agenda/proposed
mkdir -p records/raw
mkdir -p records/readable
mkdir -p records/votes
mkdir -p records/chain
mkdir -p summaries
mkdir -p meta
mkdir -p context
mkdir -p capsules
mkdir -p logs

echo "✅ Directory structure created"

# 5. Create .env template
cat > .env << 'ENVFILE'
# Bridge Arch 001 r2.1 — API Keys
# Fill in your actual keys below

ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GOOGLE_API_KEY=
XAI_API_KEY=
ENVFILE

echo "✅ .env template created (edit with: nano .env)"

# 6. Create .gitignore
cat > .gitignore << 'GITIGNORE'
.env
*.pyc
__pycache__/
logs/
capsules/
GITIGNORE

echo "✅ .gitignore created"

# 7. Initialize Git repo for backup
apt install -y git
git init
git add .gitignore
git commit -m "Initial: Bridge Arch 001 r2.1 directory structure"

echo ""
echo "═══════════════════════════════════════════════════"
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit API keys:  nano .env"
echo "  2. Upload files:   (use scp or paste)"
echo "     - bridge_arch_daemon.py"
echo "     - agenda/pending.json"
echo "     - context/*.md"
echo "  3. Test:           python3 bridge_arch_daemon.py --once"
echo "  4. Run daemon:     nohup python3 bridge_arch_daemon.py --daemon &"
echo "  5. Check logs:     tail -f logs/daemon.log"
echo "═══════════════════════════════════════════════════"
