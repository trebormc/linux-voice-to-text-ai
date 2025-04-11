#!/usr/bin/env python3
import torch
from faster_whisper import WhisperModel
from flask import Flask, request, jsonify, Response
import os
import signal
import logging
import sys
import subprocess
import time
import json
from threading import Lock

# Ensure output is not buffered
sys.stdout.reconfigure(line_buffering=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Path constants
PID_FILE_PATH = os.path.expanduser("~/.whisper_server.pid")
TEMP_FILE_PREFIX = "/tmp/whisper_temp"

# Streaming context
STREAMING_CONTEXT = {
    "previous_text": "",
    "session_active": False,
    "last_segment_time": 0,
    "accumulated_text": ""
}
context_lock = Lock()

def initialize_model():
    print("Loading Faster-Whisper large-v3-turbo model... This may take several minutes on first run")
    sys.stdout.flush()

    model_path = os.path.expanduser("~/.cache/huggingface/hub")
    if not os.path.exists(os.path.join(model_path, "models--Systran--faster-whisper-large-v3-turbo")):
        print("Downloading model files (this will happen only once)...")
        print("The large-v3-turbo model is ~10GB. Please be patient.")
        sys.stdout.flush()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}")
    sys.stdout.flush()

    model_id = "large-v3-turbo"

    # Add timestamp to measure loading time
    start_time = time.time()
    model = WhisperModel(
        model_id,
        device=device,
        compute_type="float16" if device == "cuda" else "int8",
        num_workers=4  # Increased from 2 for better performance
    )

    load_time = time.time() - start_time
    print(f"Model loaded successfully in {load_time:.2f} seconds")
    logger.info(f"Model loaded on {device} in {load_time:.2f} seconds")
    sys.stdout.flush()
    return model

# Initialize model on startup
pipe = initialize_model()

# Save PID to verify server is running
with open(PID_FILE_PATH, "w") as pid_file:
    pid_file.write(str(os.getpid()))

@app.route('/transcribe', methods=['POST'])
def transcribe():
    """Transcribe audio file using Whisper model."""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    audio_file = request.files['file']
    language = request.form.get('language', 'en')  # Default to English

    # Save file temporarily
    temp_path = f"{TEMP_FILE_PREFIX}_{os.getpid()}.flac"
    audio_file.save(temp_path)

    try:
        segments, _ = pipe.transcribe(
            temp_path,
            language=language,
            beam_size=2,
            vad_filter=True,  # Filter silences for faster processing
            word_timestamps=False,
            # condition_on_previous_text=False,
            # temperature=0.0
        )
        text = " ".join(segment.text for segment in segments)
        return jsonify({"text": text})
    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        return jsonify({"error": "Transcription failed"}), 500
    finally:
        # Clean up temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route('/stream-start', methods=['POST'])
def stream_start():
    """Initialize a new streaming session"""
    with context_lock:
        STREAMING_CONTEXT["previous_text"] = ""
        STREAMING_CONTEXT["session_active"] = True
        STREAMING_CONTEXT["last_segment_time"] = time.time()
        STREAMING_CONTEXT["accumulated_text"] = ""

    return jsonify({"status": "streaming session started"})

@app.route('/stream-end', methods=['POST'])
def stream_end():
    """End streaming session and return final transcript"""
    with context_lock:
        STREAMING_CONTEXT["session_active"] = False
        final_text = STREAMING_CONTEXT["accumulated_text"]
        STREAMING_CONTEXT["accumulated_text"] = ""

    return jsonify({"status": "streaming ended", "final_text": final_text})

@app.route('/stream-transcribe', methods=['POST'])
def stream_transcribe():
    """Transcribe a chunk of audio in streaming mode"""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    audio_file = request.files['file']
    language = request.form.get('language', 'en')

    # Get the current context
    with context_lock:
        previous_text = STREAMING_CONTEXT["previous_text"]

    # Save file temporarily
    temp_path = f"{TEMP_FILE_PREFIX}_stream_{os.getpid()}.flac"
    audio_file.save(temp_path)

    try:
        segments, _ = pipe.transcribe(
            temp_path,
            language=language,
            beam_size=1,  # Lower beam size for faster processing
            vad_filter=True,
            word_timestamps=False,
            initial_prompt=previous_text,  # Use previous text as context
            temperature=0.0
        )

        # Extract text from segments
        segment_texts = [segment.text for segment in segments]
        current_text = " ".join(segment_texts)

        # Update the streaming context
        with context_lock:
            # Keep track of the complete accumulated text
            if segment_texts:
                # Only add if we got actual content
                if STREAMING_CONTEXT["accumulated_text"]:
                    STREAMING_CONTEXT["accumulated_text"] += " " + current_text
                else:
                    STREAMING_CONTEXT["accumulated_text"] = current_text

            # Update context for next chunk
            if current_text.strip():  # Only update if we got actual content
                STREAMING_CONTEXT["previous_text"] = current_text
            STREAMING_CONTEXT["last_segment_time"] = time.time()

        return jsonify({
            "text": current_text,
            "accumulated_text": STREAMING_CONTEXT["accumulated_text"]
        })
    except Exception as e:
        logger.error(f"Streaming transcription error: {str(e)}")
        return jsonify({"error": f"Streaming transcription failed: {str(e)}"}), 500
    finally:
        # Clean up temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route('/health', methods=['GET'])
def health_check():
    """Simple health check endpoint to verify server is running."""
    return jsonify({"status": "ok", "model": "large-v3-turbo"}), 200

def signal_handler(sig, frame):
    """Handle shutdown signals gracefully."""
    logger.info('Shutting down Whisper server...')
    if os.path.exists(PID_FILE_PATH):
        os.remove(PID_FILE_PATH)
    os._exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == '__main__':
    # Ensure Flask is available
    try:
        # Run server with threaded=True for better performance with multiple requests
        app.run(host='127.0.0.1', port=5000, threaded=True)
    except ModuleNotFoundError:
        logger.info("Installing Flask...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
        app.run(host='127.0.0.1', port=5000, threaded=True)
