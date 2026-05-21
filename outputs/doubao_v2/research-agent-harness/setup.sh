#!/bin/bash

# Research Agent Harness Setup Script

echo "Setting up Research Agent Harness..."

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $PYTHON_VERSION"

if [[ "$PYTHON_VERSION" < "3.11" ]]; then
    echo "❌ Python 3.11+ is required"
    exit 1
fi

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install openai httpx

# Test the installation
echo "Testing installation..."
python -c "import sys; sys.path.insert(0, '.'); from harness import ToolRegistry, ContextManager; print('✅ Import successful')"

echo ""
echo "✅ Setup complete!"
echo ""
echo "Usage:"
echo "  source venv/bin/activate"
echo "  python -m harness -p 'Your research question' --output-dir ./output/"
echo ""
