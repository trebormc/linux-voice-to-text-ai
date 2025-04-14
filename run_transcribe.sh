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

# Asegurar que el servidor Whisper esté funcionando
ensure_whisper_server() {
    if [[ "${ENABLE_LOCAL_WHISPER:-false}" != "true" ]]; then
        return 0
    fi

    # Verificar si el servidor ya está en ejecución
    if [[ -f "$SERVER_PID_FILE" ]]; then
        local pid
        pid=$(<"$SERVER_PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "El servidor Whisper ya está en ejecución con PID $pid."
            return 0
        else
            echo "El archivo PID del servidor Whisper existe, pero el servidor no está en ejecución. Se iniciará el servidor."
            rm -f "$SERVER_PID_FILE"
        fi
    fi

    # Iniciar el servidor en segundo plano
    echo "Iniciando servidor Whisper..."
    source "$VENV_DIR/bin/activate"

    nohup python3 "${SCRIPT_DIR}/whisper_server.py" > "${HOME}/whisper_server.log" 2>&1 &

    # Almacenar PID y esperar a que el servidor inicie
    local server_pid=$!
    echo "$server_pid" > "$SERVER_PID_FILE"

    # Esperar a que el servidor esté listo
    echo "Esperando a que el servidor Whisper se inicialice..."
    local attempts=0
    local max_attempts=30  # Dar más tiempo para la inicialización

    while [[ $attempts -lt $max_attempts ]]; do
        if curl -s "http://127.0.0.1:5000/health" >/dev/null 2>&1; then
            echo "Servidor Whisper iniciado correctamente."
            break
        fi

        # Verificar si el proceso sigue en ejecución
        if ! kill -0 $server_pid 2>/dev/null; then
            echo "Error: El proceso del servidor Whisper se terminó inesperadamente."
            cat "${HOME}/whisper_server.log"
            return 1
        fi

        echo "Esperando a que el servidor responda (intento $((attempts+1))/$max_attempts)..."
        sleep 3  # Tiempo más largo entre intentos
        ((attempts++))
    done

    if [[ $attempts -eq $max_attempts ]]; then
        echo "Error: Tiempo de espera agotado esperando a que el servidor Whisper inicie."
        echo "Revise el log en ${HOME}/whisper_server.log para más detalles."
        return 1
    fi

    deactivate
}

# Verificar ENABLE_LOCAL_WHISPER antes de iniciar el servidor
if [[ "${ENABLE_LOCAL_WHISPER:-false}" == "true" ]]; then
    ensure_whisper_server

    # Si el servidor no se pudo iniciar, no intentar ejecutar el script
    if [ $? -ne 0 ]; then
        echo "No se pudo iniciar el servidor Whisper. No se puede continuar."
        exit 1
    fi
fi

# Activar el entorno virtual
source "$VENV_DIR/bin/activate"

# Ejecutar el script Python
python3 "$SCRIPT_DIR/realtime_transcribe.py" "$@"

# Desactivar el entorno virtual al finalizar
deactivate
