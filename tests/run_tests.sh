#!/bin/bash
# Test runner script for Highway Ramp Detection tests

echo "======================================================================"
echo "RUNNING GOOGLE VALIDATION TESTS"
echo "======================================================================"
echo ""

cd "$(dirname "$0")/.."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Run tests
python -m unittest tests.test_google_validation -v

echo ""
echo "======================================================================"
echo "TESTS COMPLETE"
echo "======================================================================"
