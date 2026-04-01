#!/bin/bash
# 1. Enter the virtual environment
source venv/bin/activate

# 2. Force the environment to see Homebrew binaries
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# 3. Run the app
python main.py