#!/bin/bash
#
# Generic Deployment Script for EV Smart Charger
# Works on any machine by detecting git repository root
#
# NO HARDCODED PATHS - Everything is auto-detected!
#

set -e

# Configuration
RPI_HOST="peccz@100.100.118.62"

echo "=================================================="
echo "Generic EV Smart Charger Deployment to RPi"
echo "=================================================="

# Step 1: Detect local git root
echo "✓ Step 1: Detecting local git repository root..."
LOCAL_GIT_ROOT=$(git rev-parse --show-toplevel)
echo "  Local:  $LOCAL_GIT_ROOT"

# Step 2: Detect remote git root (on RPi)
echo "✓ Step 2: Detecting RPi git repository root..."
RPI_GIT_ROOT=$(ssh "$RPI_HOST" "cd ~ && find . -maxdepth 3 -name '.git' -type d 2>/dev/null | grep ev_smart_charger | head -1 | xargs dirname" || echo "")

if [ -z "$RPI_GIT_ROOT" ]; then
    echo "  No existing installation found on RPi. Creating new..."
    # Clone repository if it doesn't exist
    ssh "$RPI_HOST" "git clone https://github.com/Peccz/ev-smart-charger.git ~/ev_smart_charger"
    RPI_GIT_ROOT="~/ev_smart_charger"
fi

# Convert relative to absolute path
RPI_GIT_ROOT=$(ssh "$RPI_HOST" "cd $RPI_GIT_ROOT && pwd")
echo "  RPi:    $RPI_GIT_ROOT"

# Step 3: Push latest changes to GitHub
echo "✓ Step 3: Pushing latest changes to GitHub..."
if [[ -n $(git status -s) ]]; then
    git add .
    git commit -m "Auto-deploy updates" || echo "Nothing to commit"
fi
git push origin main
echo "  Changes pushed to GitHub"

# Step 4: Pull latest changes on RPi
echo "✓ Step 4: Pulling latest changes on RPi..."
ssh "$RPI_HOST" bash << ENDSSH
cd "$RPI_GIT_ROOT"
git pull origin main
ENDSSH
echo "  Code updated on RPi"

# Step 5: Copy configuration files if they exist
echo "✓ Step 5: Copying configuration files..."
if [ -f "config/settings.yaml" ]; then
    ssh "$RPI_HOST" "mkdir -p $RPI_GIT_ROOT/config"
    scp config/settings.yaml "$RPI_HOST:$RPI_GIT_ROOT/config/settings.yaml"
    echo "  settings.yaml copied"
else
    echo "  Warning: config/settings.yaml not found locally"
fi

# Step 6: Setup virtual environment if needed
echo "✓ Step 6: Setting up Python environment on RPi..."
ssh "$RPI_HOST" bash << ENDSSH
cd "$RPI_GIT_ROOT"

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    echo "  Creating virtual environment..."
    python3 -m venv venv
fi

# Install/update requirements
echo "  Installing/updating requirements..."
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt
echo "  Requirements installed"
ENDSSH

# Step 7: Deploy systemd services
echo "✓ Step 7: Deploying systemd services..."

# Copy service files to tmp first
scp ev_smart_charger.service "$RPI_HOST:/tmp/ev_smart_charger.service"
scp ev_web_app.service "$RPI_HOST:/tmp/ev_web_app.service"

# Update WorkingDirectory in service files to use detected path
ssh "$RPI_HOST" bash << ENDSSH
# Update WorkingDirectory to actual path
sed -i "s|WorkingDirectory=.*|WorkingDirectory=$RPI_GIT_ROOT/ev_smart_charger/src|" /tmp/ev_smart_charger.service
sed -i "s|ExecStart=.*|ExecStart=$RPI_GIT_ROOT/ev_smart_charger/venv/bin/python main.py|" /tmp/ev_smart_charger.service

sed -i "s|WorkingDirectory=.*|WorkingDirectory=$RPI_GIT_ROOT|" /tmp/ev_web_app.service
sed -i "s|ExecStart=.*|ExecStart=$RPI_GIT_ROOT/venv/bin/python src/web_app.py|" /tmp/ev_web_app.service

# Copy to systemd directory
sudo cp /tmp/ev_smart_charger.service /etc/systemd/system/
sudo cp /tmp/ev_web_app.service /etc/systemd/system/

# Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable ev_smart_charger.service
sudo systemctl enable ev_web_app.service

echo "  Services deployed"
ENDSSH

# Step 8: Restart services
echo "✓ Step 8: Restarting services..."
ssh "$RPI_HOST" bash << 'ENDSSH'
sudo systemctl restart ev_smart_charger.service
sudo systemctl restart ev_web_app.service
echo "  Services restarted"
ENDSSH

# Step 9: Verify services are running
echo "✓ Step 9: Verifying service status..."
sleep 3
echo ""
echo "=== Service Status on RPi ==="
ssh "$RPI_HOST" "sudo systemctl status ev_smart_charger.service --no-pager | head -n 5"
echo ""
ssh "$RPI_HOST" "sudo systemctl status ev_web_app.service --no-pager | head -n 5"
echo ""

echo "=================================================="
echo "✓ Deployment Complete!"
echo "=================================================="
echo ""
echo "PATH CONFIGURATION:"
echo "  Local:  $LOCAL_GIT_ROOT"
echo "  RPi:    $RPI_GIT_ROOT"
echo ""
echo "WEB INTERFACE:"
echo "  http://100.100.118.62:5000"
echo ""
echo "To monitor logs:"
echo "  ssh $RPI_HOST"
echo "  tail -f ~/ev_charger.log"
echo "  sudo journalctl -u ev_smart_charger.service -f"
echo "  sudo journalctl -u ev_web_app.service -f"
echo ""
