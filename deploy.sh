#!/bin/bash

# Configuration
RPI_USER="peccz"
RPI_HOST="100.100.118.62"
RPI_DIR="ev_smart_charger"
SERVICE_NAME="ev_smart_charger.service"

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
    if [ ! -d "$RPI_DIR" ]; then
        echo "Cloning repository..."
        git clone https://github.com/Peccz/ev-smart-charger.git $RPI_DIR
    fi

    cd $RPI_DIR
    
    # Backup config just in case git wipeout affects it
    cp config/settings.yaml /tmp/ev_settings_backup.yaml 2>/dev/null
    
    echo "Pulling latest changes..."
    # Force git to match remote exactly, discarding local changes to tracked files
    git fetch --all
    git reset --hard origin/main
    
    # Restore config
    if [ -f "/tmp/ev_settings_backup.yaml" ]; then
        mkdir -p config
        cp /tmp/ev_settings_backup.yaml config/settings.yaml
        echo "Restored settings.yaml"
    fi
    
    echo "Setting up Virtual Environment..."
    if [ ! -d "venv" ]; then
        python3 -m venv venv
        echo "Created new venv"
    fi
    
    # Install requirements
    ./venv/bin/pip install -r requirements.txt --quiet
    
    echo "Updating Service..."
    sudo cp $SERVICE_NAME /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable $SERVICE_NAME
    
    echo "Restarting Service..."
    sudo systemctl restart $SERVICE_NAME
EOF

if [ $? -eq 0 ]; then
    echo "Deployment commands executed"
else
    echo "Deployment failed"
    exit 1
fi

# 4. Verify Status
echo "[4/4] Verifying Service Status..."
sleep 3
ssh $RPI_USER@$RPI_HOST "sudo systemctl status $SERVICE_NAME --no-pager"

echo "======================================="
echo "   Deployment Complete!                "
echo "======================================="