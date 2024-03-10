#!/bin/bash

# Step 1: Kill the current instance of application.py
pkill -f "python3 application.py"

# Step 2: Start application.py using nohup
nohup python3 application.py &
