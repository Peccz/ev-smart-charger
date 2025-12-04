#!/bin/bash

# Configuration
RPI_USER="peccz"
RPI_HOST="100.100.118.62"
RPI_DIR="ev_smart_charger"
SERVICE_CORE="ev_smart_charger.service"
SERVICE_WEB="ev_web_app.service"

echo "======================================="
echo "   EV Smart Charger - Auto Deploy      "
echo "======================================="

# 1. Push to GitHub
echo "[1/4] Pushing to GitHub..."
if [[ -n $(git status -s) ]]; then
    git add .
    git commit -m "Auto-deploy updates" 
    git push
    if [ $? -eq 0 ]; then
        echo "Code pushed successfully"
    else
        echo "Git push failed"
        exit 1
    fi
else
    echo "No local changes to push"
fi

# 2. Copy Secrets to RPi (via SCP)
echo "[2/4] Copying configuration secrets to RPi..."
if [ -f "config/settings.yaml" ]; then
    # Create config dir if not exists
    ssh $RPI_USER@$RPI_HOST "mkdir -p $RPI_DIR/config"
    
    # SCP the file directly to destination
    scp config/settings.yaml $RPI_USER@$RPI_HOST:$RPI_DIR/config/settings.yaml
    
    if [ $? -eq 0 ]; then
        echo "Settings file copied successfully"
    else
        echo "Failed to copy settings file"
        exit 1
    fi
else
    echo "Warning: config/settings.yaml not found locally!"
fi

# 3. Deploy Code on Raspberry Pi
echo "[3/4] Deploying code on Raspberry Pi..."
echo "Connecting to $RPI_USER@$RPI_HOST..."

ssh $RPI_USER@$RPI_HOST << EOF
    RPI_DIR="ev_smart_charger"
    SERVICE_CORE="ev_smart_charger.service"
    SERVICE_WEB="ev_web_app.service"

    if [ ! -d "$RPI_DIR" ]; then
        echo "Cloning repository..."
        git clone https://github.com/Peccz/ev-smart-charger.git $RPI_DIR
    fi

    cd $RPI_DIR
    
    # Temporarily move config/settings.yaml to avoid git conflicts
    if [ -f "config/settings.yaml" ]; then
        mv config/settings.yaml /tmp/ev_settings_backup.yaml
    fi
    # Force git to match remote exactly, discarding local changes to tracked files
    git fetch --all
    git reset --hard origin/main
    # Restore config/settings.yaml (or create if it didn't exist)
    if [ -f "/tmp/ev_settings_backup.yaml" ]; then
        mkdir -p config
        mv /tmp/ev_settings_backup.yaml config/settings.yaml
        echo "Restored settings.yaml from backup."
    fi
    # --- END GIT PULL ---

    echo "Recreating Virtual Environment..."
    rm -rf venv # Ensure a clean venv
    python3 -m venv venv
    
    # Install requirements - THIS TIME, SHOW OUTPUT!
    echo "Installing Python requirements. This may take a while..."
    ./venv/bin/pip install -r requirements.txt
    
    echo "Updating Services..."
    sudo cp $SERVICE_CORE /etc/systemd/system/
    sudo cp $SERVICE_WEB /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable $SERVICE_CORE
    sudo systemctl enable $SERVICE_WEB
    
    echo "Restarting Services..."
    sudo systemctl restart $SERVICE_CORE
    sudo systemctl restart $SERVICE_WEB
EOF

# --- FORCED FILE COPY OF HTML TEMPLATES (FROM LOCAL TO RPI) ---
echo "Forcibly copying HTML templates from local to RPi..."
scp src/web/templates/index.html $RPI_USER@$RPI_HOST:$RPI_DIR/src/web/templates/index.html
scp src/web/templates/planning.html $RPI_USER@$RPI_HOST:$RPI_DIR/src/web/templates/planning.html
scp src/web/templates/settings.html $RPI_USER@$RPI_HOST:$RPI_DIR/src/web/templates/settings.html
# --- END FORCED FILE COPY ---

if [ $? -eq 0 ]; then
    echo "Deployment commands executed"
else
    echo "Deployment failed"
    exit 1
fi

# 4. Verify Status
echo "[4/4] Verifying Service Status..."
sleep 5
echo "--- Core Service ---"
ssh $RPI_USER@$RPI_HOST "sudo systemctl status $SERVICE_CORE --no-pager | head -n 3"
echo "--- Web App ---"
ssh $RPI_USER@$RPI_HOST "sudo systemctl status $SERVICE_WEB --no-pager | head -n 3"

echo "======================================="
echo "   Deployment Complete!                "
echo "   Web App: http://$RPI_HOST:5000      "
echo "======================================="
