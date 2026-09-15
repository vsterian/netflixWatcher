#!/bin/bash

# Change directory to the correct paths
cd /home/pi/repos/netflixWatcher/app/ || exit 1

# Step 1: Kill the current instance of application.py
pkill -f "python3 application.py"

# Step 2: Start application.py using nohup
nohup python3 application.py &
