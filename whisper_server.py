#!/usr/bin/env python3
import torch
from transformers import pipeline
from flask import Flask, request, jsonify
import os
import signal
import sys
import subprocess
import logging

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

def initialize_model():
    """Initialize and load the speech recognition model."""
    logger.info("Loading Whisper model...")
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    model_id = "openai/whisper-large-v3-turbo"  # Faster than large-v3

    speech_recognition_pipeline = pipeline(
        "automatic-speech-recognition",
        model=model_id,
        torch_dtype=torch.float16,
        device=device,
    )
    logger.info(f"Model loaded on {device}")
    return speech_recognition_pipeline

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
        # Process with Whisper model
        result = pipe(
            temp_path,
            chunk_length_s=15,
            batch_size=24,
            return_timestamps=False,
            generate_kwargs={"language": language}  # Pass language correctly
        )

        return jsonify({"text": result["text"]})
    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        return jsonify({"error": "Transcription failed"}), 500
    finally:
        # Clean up temporary file
        if os.path.exists(temp_path):
            os.remove(temp_path)

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
        app.run(host='127.0.0.1', port=5000)
    except ModuleNotFoundError:
        logger.info("Installing Flask...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
        app.run(host='127.0.0.1', port=5000)
