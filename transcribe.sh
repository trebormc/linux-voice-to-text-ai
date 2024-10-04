#!/usr/bin/env bash
# usage: exec ./transcribe.sh twice to start and stop recording
# Dependencies: curl, jq, parecord, xdotool, killall

set -euo pipefail
IFS=$'\n\t'

# Load configuration
source ".env"

# Configuration
readonly PID_FILE="${HOME}/.recordpid"
readonly FILE="${HOME}/.voice-to-text/recording"

start_recording() {
  mkdir -p "$(dirname "$FILE")"
  echo "Starting new recording..."
  # Use timeout to limit the recording duration
  timeout "$MAX_DURATION" parecord --channels=1 --format=s16le --rate=44100 --file-format=wav \
    --device="$AUDIO_INPUT" "$FILE.wav" \
    2>"${FILE}_error.log" >"${FILE}_output.log" &
  echo $! >"$PID_FILE"
  
  if [ -s "${FILE}_error.log" ]; then
    echo "Error starting recording. Check ${FILE}_error.log for details."
    cat "${FILE}_error.log"
    return 1
  fi
  echo "Recording started with PID $(cat "$PID_FILE"). Will stop automatically after $MAX_DURATION seconds."
}

stop_recording() {
  echo "Stopping recording..."
  if [ -s "$PID_FILE" ]; then
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

write_transcript() {
  if [ ! -f "$FILE.txt" ]; then
    echo "Transcript file not found: $FILE.txt"
    return 1
  fi
  perl -pi -e 'chomp if eof' "$FILE.txt"
  iconv -f UTF-8 -t UTF-8 -c "$FILE.txt" > "${FILE}_utf8.txt"
  LANG="${TRANSCRIPTION_LANGUAGE}_${TRANSCRIPTION_LANGUAGE^^}.UTF-8" LC_ALL="${TRANSCRIPTION_LANGUAGE}_${TRANSCRIPTION_LANGUAGE^^}.UTF-8" xdotool type --clearmodifiers --file "${FILE}_utf8.txt"
  rm -f "${FILE}_utf8.txt"
}

transcribe_with_openai() {
  if [ ! -f "$FILE.wav" ]; then
    echo "Audio file not found: $FILE.wav"
    return 1
  fi
  echo "Transcribing with OpenAI..."
  curl --silent --fail --request POST \
    --url https://api.openai.com/v1/audio/transcriptions \
    --header "Authorization: Bearer $OPEN_AI_TOKEN" \
    --header 'Content-Type: multipart/form-data' \
    --form file="@$FILE.wav" \
    --form model="$OPENAI_MODEL" \
    --form response_format=text \
    --form temperature=0.0 \
    --form language="$TRANSCRIPTION_LANGUAGE" \
    -o "${FILE}.txt"
  echo "Transcription completed."
}

transcribe_with_deepgram() {
  if [ ! -f "$FILE.wav" ]; then
    echo "Audio file not found: $FILE.wav"
    return 1
  fi
  echo "Transcribing with Deepgram..."

  # Construct the full URL
  FULL_DEEPGRAM_URL="https://api.deepgram.com/v1/listen?${DEEPGRAM_PARAMS}&language=${TRANSCRIPTION_LANGUAGE}"

  curl --silent --fail --request POST \
    --url "${FULL_DEEPGRAM_URL}" \
    --header "Authorization: Token ${DEEPGRAM_TOKEN}" \
    --header 'Content-Type: audio/wav' \
    --data-binary "@$FILE.wav" \
    -o "${FILE}.json"

  jq '.results.channels[0].alternatives[0].transcript' -r "${FILE}.json" >"${FILE}.txt"
  echo "Transcription completed."
}

transcript() {
  set +u
  if [[ -z "$DEEPGRAM_TOKEN" ]]; then
    transcribe_with_openai
  else
    transcribe_with_deepgram
  fi
  set -u
}

sanity_check() {
  for cmd in xdotool parecord killall jq curl; do
    if ! command -v "$cmd" &>/dev/null; then
      echo >&2 "Error: command $cmd not found."
      exit 1
    fi
  done
  set +u
  if [[ -z "$DEEPGRAM_TOKEN" ]] && [[ -z "$OPEN_AI_TOKEN" ]]; then
    echo >&2 "You must set the DEEPGRAM_TOKEN or OPEN_AI_TOKEN environment variable."
    exit 1
  fi
  set -u
}

main() {
  sanity_check

  if [[ -f "$PID_FILE" ]]; then
    paplay "$SOUND_STOP_RECORDING" || true
    stop_recording
    transcript
    write_transcript
    rm -f "$FILE.wav" "$FILE.txt" "${FILE}_error.log" "${FILE}_output.log"
    paplay "$SOUND_END_TRANSCRIPTION" || true
  else
    start_recording
    paplay "$SOUND_START_RECORDING" || true
  fi
}

main