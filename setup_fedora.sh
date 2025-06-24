#!/bin/bash

# Installation script for Fedora 43 with Wayland support

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="${HOME}/virtualenvs/whisper-env"

# Check system dependencies for Fedora
echo "Checking system dependencies..."
sudo dnf install -y python3-virtualenv python3-pip pulseaudio-utils jq curl ffmpeg wl-clipboard ydotool

# Note: ydotool is the Wayland alternative to xdotool
# It requires additional setup for keyboard shortcuts

# Create and configure virtual environment
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating virtual environment for Whisper..."
    python3 -m venv "$VENV_DIR"
fi

# Activate and install dependencies
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install faster-whisper torch flask requests python-dotenv
deactivate

echo "Virtual environment configured."

# Make scripts executable
chmod +x "${SCRIPT_DIR}/transcribe.py"
chmod +x "${SCRIPT_DIR}/transcribe.sh"
chmod +x "${SCRIPT_DIR}/transcribe_fedora.sh"

# Setup ydotool for Wayland (optional)
echo ""
echo "NOTE: For automatic pasting on Wayland, ydotool requires additional setup:"
echo "1. Add your user to the input group: sudo usermod -aG input $USER"
echo "2. Start ydotoold service: systemctl --user enable --now ydotoold"
echo "3. Logout and login again for group changes to take effect"
echo ""
echo "Alternatively, you can disable automatic pasting by setting CLIPBOARD_AUTO_PASTE=false in .env"
echo ""
echo "Installation completed. You can run ./transcribe_fedora.sh to start transcribing."