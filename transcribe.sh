#!/bin/bash

# Directorio del script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="${HOME}/virtualenvs/whisper-env"
SERVER_PID_FILE="${HOME}/.whisper_server.pid"

# Cargar variables de entorno
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    source "${SCRIPT_DIR}/.env"
else
    echo "Error: .env file not found in ${SCRIPT_DIR}" >&2
    exit 1
fi

# Activar el entorno virtual
source "$VENV_DIR/bin/activate"

# Ejecutar el script Python
python3 "$SCRIPT_DIR/transcribe.py" "$@"

# Desactivar el entorno virtual al finalizar
deactivate
