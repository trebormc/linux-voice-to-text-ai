#!/bin/bash

# Script de instalación para realtime_transcribe.py

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="${HOME}/virtualenvs/whisper-env"

# Asegurarse de que las dependencias del sistema estén instaladas
echo "Verificando dependencias del sistema..."
sudo apt update
sudo apt install -y python3-venv python3-pip pulseaudio-utils jq curl xdotool ffmpeg

# Crear y configurar entorno virtual
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creando entorno virtual para Whisper..."
    python3 -m venv "$VENV_DIR"
fi

# Activar e instalar dependencias
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install faster-whisper torch flask requests python-dotenv
deactivate

echo "Entorno virtual configurado."

# Hacer el script ejecutable
chmod +x "${SCRIPT_DIR}/transcribe.py"
chmod +x "${SCRIPT_DIR}/transcribe.sh"

echo "Instalación completada. Puede ejecutar ./transcribe.sh para comenzar a transcribir."
