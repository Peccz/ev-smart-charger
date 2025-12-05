#!/bin/bash

# Configuration
RPI_USER="peccz"
RPI_HOST="100.100.118.62"
RPI_DIR="ev_smart_charger"
SERVICE_CORE="ev_smart_charger.service"
SERVICE_WEB="ev_web_app.service"

echo "======================================="
echo "   EV Smart Charger - AUTO DEPLOY (CLEAN INSTALL)   "
echo "======================================="

# 1. Push to GitHub (ensure local changes are pushed)
echo "[1/5] Pushing latest local changes to GitHub..."
if [[ -n $(git status -s) ]]; then
    git add .
    git commit -m "Auto-deploy updates (Clean Install Prep)" 
    git push
    if [ $? -eq 0 ]; then
        echo "Code pushed successfully."
    else
        echo "Git push failed. Please resolve manually and re-run."
        exit 1
    fi
else
    echo "No local changes to push."
fi

# 2. Clone or Update repository on RPi
echo "[2/5] Updating repository on Raspberry Pi..."
ssh $RPI_USER@$RPI_HOST << EOF
    if [ -d "$RPI_DIR" ]; then
        echo "Directory exists. Pulling latest changes..."
        cd $RPI_DIR
        git fetch origin
        git reset --hard origin/main
    else
        echo "Cloning repository..."
        git clone https://github.com/Peccz/ev-smart-charger.git $RPI_DIR
    fi
EOF

if [ $? -ne 0 ]; then
    echo "Error: Failed to update repository."
    exit 1
fi

# 3. Copy Secrets to RPi (via SCP)
echo "[3/5] Copying configuration secrets to RPi..."
if [ -f "config/settings.yaml" ]; then
    # Create config dir if not exists (in new clone)
    ssh $RPI_USER@$RPI_HOST "mkdir -p $RPI_DIR/data" # Ensure data dir exists for user_settings
    ssh $RPI_USER@$RPI_HOST "mkdir -p $RPI_DIR/config" 
    
    # SCP the file directly to destination
    scp config/settings.yaml $RPI_USER@$RPI_HOST:$RPI_DIR/config/settings.yaml
    if [ $? -ne 0 ]; then
        echo "Error: Failed to copy settings file."
        exit 1
    fi
    echo "Settings file copied successfully."
    
    # Copy user_settings.json if it exists
    if [ -f "data/user_settings.json" ]; then
        echo "Copying user_settings.json..."
        scp data/user_settings.json $RPI_USER@$RPI_HOST:$RPI_DIR/data/user_settings.json
        if [ $? -ne 0 ]; then
             echo "Warning: Failed to copy user_settings.json"
        else
             echo "user_settings.json copied successfully."
        fi
    fi
else
    echo "Warning: config/settings.yaml not found locally. Please create it."
    exit 1
fi

# 4. Set up Venv and install on RPi
echo "[4/5] Setting up Virtual Environment and installing requirements on RPi..."
ssh $RPI_USER@$RPI_HOST << EOF
    cd $RPI_DIR
    echo "Creating virtual environment..."
    python3 -m venv venv
    
    echo "Installing Python requirements. This may take a while..."
    ./venv/bin/pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "Error: Failed to install Python requirements."
        exit 1
    fi
EOF
if [ $? -ne 0 ]; then
    echo "Error: Virtual environment setup failed."
    exit 1
fi

# 5. Copy Service files and Start Services on RPi
echo "[5/5] Copying service files and starting services on RPi..."
scp ev_smart_charger.service $RPI_USER@$RPI_HOST:/tmp/ev_smart_charger.service
scp ev_web_app.service $RPI_USER@$RPI_HOST:/tmp/ev_web_app.service
if [ $? -ne 0 ]; then
    echo "Error: Failed to copy service files."
    exit 1
fi

ssh $RPI_USER@$RPI_HOST << EOF
    sudo cp /tmp/ev_smart_charger.service /etc/systemd/system/
    sudo cp /tmp/ev_web_app.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable $SERVICE_CORE
    sudo systemctl enable $SERVICE_WEB
    
    echo "Starting services..."
    sudo systemctl start $SERVICE_CORE
    sudo systemctl start $SERVICE_WEB
EOF
if [ $? -ne 0 ]; then
    echo "Error: Failed to start services."
    exit 1
fi

# 6. Verify Status
echo "Verifying Service Status..."
sleep 5
echo "--- Core Service ---"
ssh $RPI_USER@$RPI_HOST "sudo systemctl status $SERVICE_CORE --no-pager | head -n 3"
echo "--- Web App ---"
ssh $RPI_USER@$RPI_HOST "sudo systemctl status $SERVICE_WEB --no-pager | head -n 3"

echo "======================================="
echo "   Clean Install & Deployment Complete!                "
echo "   Web App: http://$RPI_HOST:5000      "
echo "======================================="