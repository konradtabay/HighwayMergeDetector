#!/bin/bash
# Highway Ramp Detection System - macOS/Linux Setup Script
# By Konrad Tabay - tabay.konrad@gmail.com

echo ""
echo "======================================================================"
echo "HIGHWAY RAMP DETECTION SYSTEM - SETUP"
echo "======================================================================"
echo ""
echo "Installing dependencies..."
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    echo "Please install Python 3.7+ from https://www.python.org/downloads/"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
REQUIRED_VERSION="3.7"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "ERROR: Python $PYTHON_VERSION is installed, but Python $REQUIRED_VERSION or higher is required"
    exit 1
fi

# Install requirements
pip3 install -r requirements.txt
if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Failed to install dependencies"
    exit 1
fi

echo ""
echo "======================================================================"
echo "SETUP COMPLETE!"
echo "======================================================================"
echo ""
echo "Quick Start:"
echo "  1. Place GPS files in input/ directory"
echo "  2. Run: python3 batch_process_trips.py"
echo "  3. Visualize: python3 visualize_server.py"
echo ""
echo "For single trip analysis:"
echo "  python3 highway_ramp_detector.py"
echo ""
echo "Documentation: README.md"
echo "Support: tabay.konrad@gmail.com"
echo "======================================================================"
echo ""

