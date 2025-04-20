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
readonly MAX_DURATION="${MAX_DURATION:-120}"
readonly AUDIO_INPUT="${AUDIO_INPUT:-@DEFAULT_SOURCE@}"
readonly TRANSCRIPTION_LANGUAGE="${TRANSCRIPTION_LANGUAGE:-en}"
readonly OPENAI_MODEL="${OPENAI_MODEL:-whisper-1}"
readonly DEEPGRAM_PARAMS="${DEEPGRAM_PARAMS:-smart_format=true&paragraphs=true&punctuate=true&model=nova-2}"
readonly AUDIO_FORMAT="${AUDIO_FORMAT:-flac}"
readonly AUDIO_CHANNELS="${AUDIO_CHANNELS:-1}"
readonly AUDIO_SAMPLE_RATE="${AUDIO_SAMPLE_RATE:-16000}"
readonly CLIPBOARD_AUTO_PASTE="${CLIPBOARD_AUTO_PASTE:-true}"
readonly NOTIFICATION_SOUND_ENABLED="${NOTIFICATION_SOUND_ENABLED:-true}"

command_exists() {
    command -v "$1" &> /dev/null
}

start_recording() {
    mkdir -p "$(dirname "$FILE")"
    echo "Starting new recording..."
    timeout "$MAX_DURATION" parecord --channels="$AUDIO_CHANNELS" --format=s16le --rate="$AUDIO_SAMPLE_RATE" \
        --device="$AUDIO_INPUT" "$FILE.$AUDIO_FORMAT" \
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
    if [[ "${CLIPBOARD_AUTO_PASTE}" != "true" ]]; then
        echo "Auto-paste is disabled. Please paste manually."
        return 0
    fi

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

    if copy_to_clipboard < "${FILE}_utf8.txt"; then
        echo "Transcript copied to clipboard."

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
    if [[ ! -f "$FILE.$AUDIO_FORMAT" ]]; then
        echo "Audio file not found: $FILE.$AUDIO_FORMAT" >&2
        return 1
    fi
    echo "Transcribing with OpenAI..."
    if ! curl --silent --fail --request POST \
        --url https://api.openai.com/v1/audio/transcriptions \
        --header "Authorization: Bearer $OPEN_AI_TOKEN" \
        --header 'Content-Type: multipart/form-data' \
        --form file="@$FILE.$AUDIO_FORMAT" \
        --form model="$OPENAI_MODEL" \
        --form response_format=text \
        --form temperature="${TRANSCRIPTION_TEMPERATURE:-0.0}" \
        --form language="$TRANSCRIPTION_LANGUAGE" \
        -o "${FILE}.txt"; then
        echo "Error: OpenAI transcription failed." >&2
        return 1
    fi
    echo "Transcription completed."
}

transcribe_with_deepgram() {
    if [[ ! -f "$FILE.$AUDIO_FORMAT" ]]; then
        echo "Audio file not found: $FILE.$AUDIO_FORMAT" >&2
        return 1
    fi
    echo "Transcribing with Deepgram..."

    local FULL_DEEPGRAM_URL="https://api.deepgram.com/v1/listen?${DEEPGRAM_PARAMS}&language=${TRANSCRIPTION_LANGUAGE}"

    if ! curl --silent --fail --request POST \
        --url "${FULL_DEEPGRAM_URL}" \
        --header "Authorization: Token ${DEEPGRAM_TOKEN}" \
        --header "Content-Type: audio/$AUDIO_FORMAT" \
        --data-binary "@$FILE.$AUDIO_FORMAT" \
        -o "${FILE}.json"; then
        echo "Error: Deepgram transcription failed." >&2
        return 1
    fi

    jq '.results.channels[0].alternatives[0].transcript' -r "${FILE}.json" > "${FILE}.txt"
    echo "Transcription completed."
}

transcribe_with_local_whisper() {
    if [[ ! -f "$FILE.$AUDIO_FORMAT" ]]; then
        echo "Audio file not found: $FILE.$AUDIO_FORMAT" >&2
        return 1
    fi
    echo "Transcribing with Local Whisper..."

    # Build parameters for the Python script
    local params=(
        "$FILE.$AUDIO_FORMAT"
        "$TRANSCRIPTION_LANGUAGE"
    )

    # Add transcription options if defined
    [[ -n "${TRANSCRIPTION_TIMESTAMPS:-}" ]] && params+=("--timestamps=${TRANSCRIPTION_TIMESTAMPS}")
    [[ -n "${TRANSCRIPTION_DIARIZATION:-}" ]] && params+=("--diarization=${TRANSCRIPTION_DIARIZATION}")
    [[ -n "${TRANSCRIPTION_RETURN_SEGMENTS:-}" ]] && params+=("--return_segments=${TRANSCRIPTION_RETURN_SEGMENTS}")
    [[ -n "${TRANSCRIPTION_INITIAL_PROMPT:-}" ]] && params+=("--initial_prompt=${TRANSCRIPTION_INITIAL_PROMPT}")
    [[ -n "${TRANSCRIPTION_TEMPERATURE:-}" ]] && params+=("--temperature=${TRANSCRIPTION_TEMPERATURE}")
    [[ -n "${TRANSCRIPTION_BEAM_SIZE:-}" ]] && params+=("--beam_size=${TRANSCRIPTION_BEAM_SIZE}")

    # Call Python script
    if ! python3 "${SCRIPT_DIR}/transcribe_audio.py" "${params[@]}"; then
        echo "Error: Local Whisper transcription failed." >&2
        return 1
    fi

    # The Python script already saves the result to $FILE.txt
    echo "Local transcription completed."
}

transcribe() {
    if [[ "${ENABLE_LOCAL_WHISPER:-false}" == "true" ]]; then
        transcribe_with_local_whisper
    elif [[ -n "${DEEPGRAM_TOKEN:-}" ]]; then
        transcribe_with_deepgram
    elif [[ -n "${OPEN_AI_TOKEN:-}" ]]; then
        transcribe_with_openai
    else
        echo "Error: No transcription service configured." >&2
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

    if [[ "${ENABLE_LOCAL_WHISPER:-false}" != "true" ]] && [[ -z "${DEEPGRAM_TOKEN:-}" ]] && [[ -z "${OPEN_AI_TOKEN:-}" ]]; then
            echo "Error: You must either enable local Whisper or set DEEPGRAM_TOKEN or OPEN_AI_TOKEN environment variable." >&2
            exit 1
        fi

}

play_sound() {
    if [[ "${NOTIFICATION_SOUND_ENABLED:-true}" != "true" ]]; then
        return 0
    fi

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
        rm -f "$FILE.$AUDIO_FORMAT" "$FILE.txt" "${FILE}_error.log" "${FILE}_output.log"
        play_sound "$SOUND_END_TRANSCRIPTION"
    else
        start_recording
        play_sound "$SOUND_START_RECORDING"
    fi
}

main
