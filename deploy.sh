#!/bin/bash

# Configuration
RPI_USER="peccz"
RPI_HOST="100.100.118.62"
RPI_DIR="ev_smart_charger"
SERVICE_NAME="ev_smart_charger.service"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${YELLOW}=======================================${NC}"
echo -e "${YELLOW}   EV Smart Charger - Auto Deploy      ${NC}"
echo -e "${YELLOW}=======================================${NC}"

# 1. Push to GitHub
echo -e "\n${YELLOW}[1/3] Pushing to GitHub...${NC}"
if [[ -n $(git status -s) ]]; then
    git add .
    # Use a default message if running non-interactively
    git commit -m "Auto-deploy updates" 
    git push
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Code pushed successfully${NC}"
    else
        echo -e "${RED}✗ Git push failed${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ No local changes to push${NC}"
fi

# 2. Deploy to Raspberry Pi
echo -e "\n${YELLOW}[2/3] Deploying to Raspberry Pi...${NC}"
echo "Connecting to $RPI_USER@$RPI_HOST..."

ssh $RPI_USER@$RPI_HOST << EOF
    # Create directory if it doesn't exist
    if [ ! -d "$RPI_DIR" ]; then
        echo "Cloning repository..."
        git clone https://github.com/Peccz/ev-smart-charger.git $RPI_DIR
    fi

    cd $RPI_DIR
    
    echo "Pulling latest changes..."
    git pull
    
    echo "Setting up Virtual Environment..."
    # Create venv if it doesn't exist
    if [ ! -d "venv" ]; then
        python3 -m venv venv
        echo "Created new venv"
    fi
    
    # Install requirements inside venv
    ./venv/bin/pip install -r requirements.txt --quiet
    
    echo "Updating Service..."
    # Copy service file to systemd
    sudo cp $SERVICE_NAME /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable $SERVICE_NAME
    
    echo "Restarting Service..."
    sudo systemctl restart $SERVICE_NAME
EOF

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Deployment commands executed${NC}"
else
    echo -e "${RED}✗ Deployment failed${NC}"
    exit 1
fi

# 3. Verify Status
echo -e "\n${YELLOW}[3/3] Verifying Service Status...${NC}"
# Wait a moment for service to start up or fail
sleep 3
ssh $RPI_USER@$RPI_HOST "sudo systemctl status $SERVICE_NAME --no-pager"

echo -e "\n${GREEN}=======================================${NC}"
echo -e "${GREEN}   🚀 Deployment Complete!             ${NC}"
echo -e "${GREEN}=======================================${NC}"