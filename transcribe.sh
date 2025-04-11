#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
VENV_DIR="${HOME}/virtualenvs/whisper-env"
SERVER_PID_FILE="${HOME}/.whisper_server.pid"

# Load configuration
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    source "${SCRIPT_DIR}/.env"
else
    echo "Error: .env file not found in ${SCRIPT_DIR}" >&2
    exit 1
fi

# Configuration
readonly FILE="${HOME}/.voice-to-text/recording"
readonly AUDIO_INPUT="${AUDIO_INPUT:-@DEFAULT_SOURCE@}"
readonly TRANSCRIPTION_LANGUAGE="${TRANSCRIPTION_LANGUAGE:-en}"
readonly AUDIO_FORMAT="flac"
readonly STREAM_SEGMENT_DURATION=3  # Duración de cada segmento en segundos
readonly STREAMING_TEMP_DIR="${HOME}/.voice-to-text/temp_segments"
readonly STREAMING_OUTPUT_FILE="${HOME}/.voice-to-text/streaming_output.txt"

# Setup virtual environment if needed
setup_venv() {
    if [[ ! -d "$VENV_DIR" ]]; then
        echo "Setting up virtual environment for Whisper..."
        # Check if python3-venv is installed
        if ! dpkg -l | grep -q python3-venv; then
            echo "Installing python3-venv..."
            sudo apt-get update
            sudo apt-get install -y python3-venv python3-full
        fi

        # Create virtual environment
        python3 -m venv "$VENV_DIR"

        # Activate and install dependencies
        source "$VENV_DIR/bin/activate"
        pip install --upgrade pip
        pip install faster-whisper flask requests torch
        deactivate

        echo "Virtual environment setup complete."
    fi
}

# Ensure the Whisper server is running
ensure_whisper_server() {
    if [[ "${ENABLE_LOCAL_WHISPER:-false}" != "true" ]]; then
        return 0
    fi

    # Check if server is already running
    if [[ -f "$SERVER_PID_FILE" ]]; then
        local pid
        pid=$(<"$SERVER_PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "Whisper server is already running with PID $pid."
            return 0
        else
            echo "Whisper server PID file exists but server is not running. Will start the server."
            rm -f "$SERVER_PID_FILE"
        fi
    fi

    # Start the server in the background
    echo "Starting Whisper server..."
    setup_venv
    source "$VENV_DIR/bin/activate"

    nohup python3 "${SCRIPT_DIR}/whisper_server.py" > "${HOME}/whisper_server.log" 2>&1 &

    # Store PID and wait for the server to start
    local server_pid=$!
    echo "$server_pid" > "$SERVER_PID_FILE"

    # Wait for server to be ready
    echo "Waiting for Whisper server to initialize..."
    local attempts=0
    local max_attempts=20

    while [[ $attempts -lt $max_attempts ]]; do
        if curl -s "http://127.0.0.1:5000/health" >/dev/null 2>&1; then
            echo "Whisper server started successfully."
            break
        fi

        # Check if process is still running
        if ! kill -0 $server_pid 2>/dev/null; then
            echo "Error: Whisper server process terminated unexpectedly."
            cat "${HOME}/whisper_server.log"
            return 1
        fi

        echo "Waiting for server to become responsive (attempt $((attempts+1))/$max_attempts)..."
        sleep 2
        ((attempts++))
    done

    if [[ $attempts -eq $max_attempts ]]; then
        echo "Error: Timed out waiting for Whisper server to start."
        return 1
    fi
}

command_exists() {
    command -v "$1" &> /dev/null
}

# Transcribe a single segment with local Whisper
transcribe_segment_with_local_whisper() {
    local segment_file="$1"
    local language="$2"

    if [[ ! -f "$segment_file" ]]; then
        echo ""
        return 1
    fi

    # Make API call directly to server
    local result
    result=$(curl -s -X POST \
        -F "file=@$segment_file" \
        -F "language=$language" \
        http://127.0.0.1:5000/transcribe)

    # Extract text from JSON
    echo "$result" | grep -o '"text":"[^"]*"' | sed 's/"text":"//;s/"$//'
}

# Transcribe a single segment with Deepgram
transcribe_segment_with_deepgram() {
    local segment_file="$1"

    if [[ ! -f "$segment_file" ]]; then
        echo ""
        return 1
    fi

    local temp_output="/tmp/segment_output.json"
    local FULL_DEEPGRAM_URL="https://api.deepgram.com/v1/listen?${DEEPGRAM_PARAMS:-smart_format=true&paragraphs=true&punctuate=true&model=nova-2}&language=${TRANSCRIPTION_LANGUAGE}"

    if curl --silent --fail --request POST \
        --url "${FULL_DEEPGRAM_URL}" \
        --header "Authorization: Token ${DEEPGRAM_TOKEN}" \
        --header "Content-Type: audio/$AUDIO_FORMAT" \
        --data-binary "@$segment_file" \
        -o "$temp_output"; then

        jq '.results.channels[0].alternatives[0].transcript' -r "$temp_output"
        return 0
    else
        echo ""
        return 1
    fi
}

# Transcribe a single segment with OpenAI
transcribe_segment_with_openai() {
    local segment_file="$1"

    if [[ ! -f "$segment_file" ]]; then
        echo ""
        return 1
    fi

    local temp_output="/tmp/segment_output.txt"

    if curl --silent --fail --request POST \
        --url https://api.openai.com/v1/audio/transcriptions \
        --header "Authorization: Bearer $OPEN_AI_TOKEN" \
        --header 'Content-Type: multipart/form-data' \
        --form file="@$segment_file" \
        --form model="${OPENAI_MODEL:-whisper-1}" \
        --form response_format=text \
        --form temperature=0.0 \
        --form language="$TRANSCRIPTION_LANGUAGE" \
        -o "$temp_output"; then

        cat "$temp_output"
        return 0
    else
        echo ""
        return 1
    fi
}

copy_to_clipboard() {
    if command_exists xclip; then
        xclip -selection clipboard
    elif command_exists wl-copy; then
        wl-copy
    else
        echo "Error: No clipboard tool found. Install xclip or wl-copy." >&2
        return 1
    fi
}

paste_from_clipboard() {
    if command_exists xdotool; then
        sleep 0.2
        xdotool key ctrl+v
    else
        echo "Warning: xdotool not found. Unable to paste automatically. Please paste manually." >&2
        return 1
    fi
}

play_sound() {
    local sound_file="$1"
    if command_exists paplay && [[ -f "$sound_file" ]]; then
        paplay "$sound_file" || true
    fi
}

check_dependencies() {
    local missing_commands=()
    for cmd in parecord curl jq; do
        if ! command_exists "$cmd"; then
            missing_commands+=("$cmd")
        fi
    done

    if [[ ${#missing_commands[@]} -gt 0 ]]; then
        echo "Error: The following commands are not found: ${missing_commands[*]}" >&2
        exit 1
    fi

    if [[ "${ENABLE_LOCAL_WHISPER:-false}" != "true" ]] &&
       [[ -z "${DEEPGRAM_TOKEN:-}" ]] &&
       [[ -z "${OPEN_AI_TOKEN:-}" ]]; then
        echo "Error: You must either enable local Whisper or set DEEPGRAM_TOKEN or OPEN_AI_TOKEN environment variable." >&2
        exit 1
    fi
}

interactive_record_and_transcribe() {
    # Crear directorios necesarios
    mkdir -p "$(dirname "$FILE")" "$STREAMING_TEMP_DIR"

    # Inicializar archivos de salida
    echo "" > "$STREAMING_OUTPUT_FILE"
    echo "" > "$FILE.txt"

    # Informar al usuario
    echo "Starting voice recording for transcription..."
    echo "Speak into your microphone. Press any key to stop recording."

    # Reproducir sonido de inicio si está configurado
    play_sound "$SOUND_START_RECORDING"

    # ENFOQUE ALTERNATIVO: Grabar un solo archivo largo y luego procesarlo
    # Este enfoque es más fiable que intentar grabar y procesar segmentos en paralelo

    # Archivo temporal para la grabación completa
    full_recording="${STREAMING_TEMP_DIR}/full_recording.flac"

    # Iniciar grabación en segundo plano
    parecord --channels=1 --format=s16le --rate=16000 \
        --file-format=flac \
        --device="$AUDIO_INPUT" \
        "$full_recording" > /dev/null 2>&1 &

    recording_pid=$!
    echo "Started recording process with PID $recording_pid"

    # Esperar a que el usuario presione cualquier tecla
    echo "Recording in progress. Press any key to stop recording..."
    read -n 1 -s

    # Detener el proceso de grabación
    kill $recording_pid
    wait $recording_pid 2>/dev/null || true

    # Verificar si se grabó el archivo
    if [[ ! -f "$full_recording" || ! -s "$full_recording" ]]; then
        echo "Error: No se pudo grabar audio. Verifique su micrófono."
        play_sound "$SOUND_STOP_RECORDING"
        return 1
    fi

    echo "Recording completed. Starting transcription..."
    play_sound "$SOUND_STOP_RECORDING"

    # Transcribir el archivo completo
    if [[ "${ENABLE_LOCAL_WHISPER:-false}" == "true" ]]; then
        echo "Transcribing with Local Whisper..."
        source "$VENV_DIR/bin/activate"
        python3 "${SCRIPT_DIR}/transcribe_audio.py" "$full_recording" "$TRANSCRIPTION_LANGUAGE"
        deactivate

        # Obtener el resultado
        txt_file="${full_recording%.*}.txt"
        if [[ -f "$txt_file" ]]; then
            cat "$txt_file" > "$FILE.txt"
        fi
    elif [[ -n "${DEEPGRAM_TOKEN:-}" ]]; then
        echo "Transcribing with Deepgram..."
        local temp_output="${STREAMING_TEMP_DIR}/output.json"
        local FULL_DEEPGRAM_URL="https://api.deepgram.com/v1/listen?${DEEPGRAM_PARAMS:-smart_format=true&paragraphs=true&punctuate=true&model=nova-2}&language=${TRANSCRIPTION_LANGUAGE}"

        curl -s -X POST \
            -H "Authorization: Token ${DEEPGRAM_TOKEN}" \
            -H "Content-Type: audio/$AUDIO_FORMAT" \
            --data-binary "@$full_recording" \
            "$FULL_DEEPGRAM_URL" \
            -o "$temp_output"

        jq '.results.channels[0].alternatives[0].transcript' -r "$temp_output" > "$FILE.txt"
    elif [[ -n "${OPEN_AI_TOKEN:-}" ]]; then
        echo "Transcribing with OpenAI..."
        curl -s -X POST \
            -H "Authorization: Bearer $OPEN_AI_TOKEN" \
            -H "Content-Type: multipart/form-data" \
            -F "file=@$full_recording" \
            -F "model=${OPENAI_MODEL:-whisper-1}" \
            -F "response_format=text" \
            -F "temperature=0.0" \
            -F "language=$TRANSCRIPTION_LANGUAGE" \
            "https://api.openai.com/v1/audio/transcriptions" \
            -o "$FILE.txt"
    else
        echo "Error: No transcription service configured."
        return 1
    fi

    echo "Transcription completed."
    echo "Final transcript:"
    echo "-----------------"
    cat "$FILE.txt"
    echo "-----------------"

    # Copiar al portapapeles
    if cat "$FILE.txt" | copy_to_clipboard; then
        echo "Transcript copied to clipboard."

        # Intentar pegar automáticamente si xdotool está disponible
        if command_exists xdotool; then
            echo "Attempting to paste automatically..."
            paste_from_clipboard && echo "Transcript pasted."
        fi
    fi

    # Reproducir sonido de finalización
    play_sound "$SOUND_END_TRANSCRIPTION"

    # Limpiar archivos temporales
    rm -rf "$STREAMING_TEMP_DIR"
}

main() {
    # Verificar dependencias
    check_dependencies

    # Asegurar que el servidor Whisper esté funcionando
    ensure_whisper_server

    # Ejecutar grabación y transcripción interactiva
    interactive_record_and_transcribe
}

main
