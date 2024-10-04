#!/usr/bin/env bash
# Usage: Execute ./transcribe.sh twice to start and stop recording
# Dependencies: curl, jq, parecord, xdotool, xclip or wl-copy (for clipboard functionality)

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Load configuration
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    source "${SCRIPT_DIR}/.env"
else
    echo "Error: .env file not found in ${SCRIPT_DIR}" >&2
    exit 1
fi

# Configuration
readonly PID_FILE="${HOME}/.recordpid"
readonly FILE="${HOME}/.voice-to-text/recording"
readonly MAX_DURATION="${MAX_DURATION:-300}"  # Default to 5 minutes if not set
readonly AUDIO_INPUT="${AUDIO_INPUT:-default}"
readonly TRANSCRIPTION_LANGUAGE="${TRANSCRIPTION_LANGUAGE:-en}"
readonly OPENAI_MODEL="${OPENAI_MODEL:-whisper-1}"
readonly DEEPGRAM_PARAMS="${DEEPGRAM_PARAMS:-model=nova}"

# Function to check if a command exists
command_exists() {
    command -v "$1" &> /dev/null
}

start_recording() {
    mkdir -p "$(dirname "$FILE")"
    echo "Starting new recording..."
    # Use timeout to limit the recording duration
    timeout "$MAX_DURATION" parecord --channels=1 --format=s16le --rate=44100 --file-format=wav \
        --device="$AUDIO_INPUT" "$FILE.wav" \
        2>"${FILE}_error.log" >"${FILE}_output.log" &
    echo $! > "$PID_FILE"
    
    if [[ -s "${FILE}_error.log" ]]; then
        echo "Error starting recording. Check ${FILE}_error.log for details." >&2
        cat "${FILE}_error.log" >&2
        return 1
    fi
    echo "Recording started with PID $(cat "$PID_FILE"). Will stop automatically after $MAX_DURATION seconds."
}

stop_recording() {
    echo "Stopping recording..."
    if [[ -s "$PID_FILE" ]]; then
        local pid
        pid=$(<"$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            timeout 5s tail --pid="$pid" -f /dev/null
            echo "Recording process $pid stopped."
        else
            echo "Process $pid not found, cleaning up..."
        fi
        rm -f "$PID_FILE"
    fi
    echo "Recording stopped."
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

write_transcript() {
    if [[ ! -f "$FILE.txt" ]]; then
        echo "Transcript file not found: $FILE.txt" >&2
        return 1
    fi
    # Remove trailing newline if present
    perl -pi -e 'chomp if eof' "$FILE.txt"
    # Ensure proper UTF-8 encoding
    iconv -f UTF-8 -t UTF-8 -c "$FILE.txt" > "${FILE}_utf8.txt"
    
    # Copy the content to clipboard
    if copy_to_clipboard < "${FILE}_utf8.txt"; then
        echo "Transcript copied to clipboard."
        
        # Try to paste the content
        if paste_from_clipboard; then
            echo "Transcript pasted."
        fi
    else
        echo "Error: Failed to copy to clipboard." >&2
        return 1
    fi
    
    rm -f "${FILE}_utf8.txt"
}

transcribe_with_openai() {
    if [[ ! -f "$FILE.wav" ]]; then
        echo "Audio file not found: $FILE.wav" >&2
        return 1
    fi
    echo "Transcribing with OpenAI..."
    if ! curl --silent --fail --request POST \
        --url https://api.openai.com/v1/audio/transcriptions \
        --header "Authorization: Bearer $OPEN_AI_TOKEN" \
        --header 'Content-Type: multipart/form-data' \
        --form file="@$FILE.wav" \
        --form model="$OPENAI_MODEL" \
        --form response_format=text \
        --form temperature=0.0 \
        --form language="$TRANSCRIPTION_LANGUAGE" \
        -o "${FILE}.txt"; then
        echo "Error: OpenAI transcription failed." >&2
        return 1
    fi
    echo "Transcription completed."
}

transcribe_with_deepgram() {
    if [[ ! -f "$FILE.wav" ]]; then
        echo "Audio file not found: $FILE.wav" >&2
        return 1
    fi
    echo "Transcribing with Deepgram..."

    # Construct the full URL
    local FULL_DEEPGRAM_URL="https://api.deepgram.com/v1/listen?${DEEPGRAM_PARAMS}&language=${TRANSCRIPTION_LANGUAGE}"

    if ! curl --silent --fail --request POST \
        --url "${FULL_DEEPGRAM_URL}" \
        --header "Authorization: Token ${DEEPGRAM_TOKEN}" \
        --header 'Content-Type: audio/wav' \
        --data-binary "@$FILE.wav" \
        -o "${FILE}.json"; then
        echo "Error: Deepgram transcription failed." >&2
        return 1
    fi

    jq '.results.channels[0].alternatives[0].transcript' -r "${FILE}.json" > "${FILE}.txt"
    # rm -f "${FILE}.json"
    echo "Transcription completed."
}

transcribe() {
    if [[ -n "${DEEPGRAM_TOKEN:-}" ]]; then
        transcribe_with_deepgram
    elif [[ -n "${OPEN_AI_TOKEN:-}" ]]; then
        transcribe_with_openai
    else
        echo "Error: Neither DEEPGRAM_TOKEN nor OPEN_AI_TOKEN is set." >&2
        return 1
    fi
}

check_clipboard_tools() {
    if ! command_exists xclip && ! command_exists wl-copy; then
        echo "Warning: No clipboard tool found. Install xclip or wl-copy for clipboard functionality." >&2
        exit 1
    fi
}

sanity_check() {
    check_clipboard_tools
  
    local missing_commands=()
    for cmd in xdotool parecord killall jq curl; do
        if ! command_exists "$cmd"; then
            missing_commands+=("$cmd")
        fi
    done
    
    if [[ ${#missing_commands[@]} -gt 0 ]]; then
        echo "Error: The following commands are not found: ${missing_commands[*]}" >&2
        exit 1
    fi

    if [[ -z "${DEEPGRAM_TOKEN:-}" ]] && [[ -z "${OPEN_AI_TOKEN:-}" ]]; then
        echo "Error: You must set either the DEEPGRAM_TOKEN or OPEN_AI_TOKEN environment variable." >&2
        exit 1
    fi
}

play_sound() {
    local sound_file="$1"
    if command_exists paplay && [[ -f "$sound_file" ]]; then
        paplay "$sound_file" || true
    fi
}

main() {
    sanity_check

    if [[ -f "$PID_FILE" ]]; then
        play_sound "$SOUND_STOP_RECORDING"
        stop_recording
        transcribe
        write_transcript
        rm -f "$FILE.wav" "$FILE.txt" "${FILE}_error.log" "${FILE}_output.log"
        play_sound "$SOUND_END_TRANSCRIPTION"
    else
        start_recording
        play_sound "$SOUND_START_RECORDING"
    fi
}

main