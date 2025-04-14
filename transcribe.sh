#!/bin/bash

# Script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VOICE_TO_TEXT_DIR="${HOME}/.voice-to-text"
VENV_DIR="${HOME}/virtualenvs/whisper-env"

# Ensure working directory exists
mkdir -p "${VOICE_TO_TEXT_DIR}"

# Load environment variables
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    source "${SCRIPT_DIR}/.env"
fi

# Check if virtual environment exists
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Error: Environment not found at $VENV_DIR"
    echo "Please create it with: python -m venv $VENV_DIR"
    echo "Then install dependencies: $VENV_DIR/bin/pip install faster-whisper torch"
    exit 1
fi

# Activate virtual environment and run Python script
source "$VENV_DIR/bin/activate"
python3 "$SCRIPT_DIR/transcribe.py"
deactivate
