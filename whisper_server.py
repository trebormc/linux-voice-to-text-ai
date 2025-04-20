#!/usr/bin/env python3
import torch
from transformers import pipeline
from flask import Flask, request, jsonify
import os
import signal
import sys
import subprocess
import logging
import dotenv
from pathlib import Path

# Load environment variables
env_path = Path(os.path.dirname(os.path.abspath(__file__))) / '.env'
dotenv.load_dotenv(dotenv_path=env_path)

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

# Get configuration from environment variables
WHISPER_MODEL_SIZE = os.getenv('WHISPER_MODEL_SIZE', 'large-v3')
WHISPER_DEVICE = os.getenv('WHISPER_DEVICE', 'auto')
WHISPER_CPU_THREADS = int(os.getenv('WHISPER_CPU_THREADS', '4'))
WHISPER_BATCH_SIZE = int(os.getenv('WHISPER_BATCH_SIZE', '24'))
WHISPER_CHUNK_LENGTH = int(os.getenv('WHISPER_CHUNK_LENGTH', '15'))
WHISPER_SERVER_HOST = os.getenv('WHISPER_SERVER_HOST', '127.0.0.1')
WHISPER_SERVER_PORT = int(os.getenv('WHISPER_SERVER_PORT', '5000'))
SERVER_TIMEOUT = int(os.getenv('SERVER_TIMEOUT', '180'))
SERVER_UNLOAD_AFTER_IDLE = int(os.getenv('SERVER_UNLOAD_AFTER_IDLE', '3600'))
AUDIO_FORMAT = os.getenv('AUDIO_FORMAT', 'flac')

def initialize_model():
    """Initialize and load the speech recognition model."""
    logger.info(f"Loading Whisper model: {WHISPER_MODEL_SIZE}...")

    # Determine device
    if WHISPER_DEVICE == 'auto':
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    elif WHISPER_DEVICE == 'cuda':
        device = "cuda:0"
    else:
        device = "cpu"

    # Set thread count for CPU computations
    if device == "cpu":
        torch.set_num_threads(WHISPER_CPU_THREADS)
        logger.info(f"Set CPU threads to {WHISPER_CPU_THREADS}")

    # Map model size to model ID
    model_mapping = {
        'tiny': 'openai/whisper-tiny',
        'base': 'openai/whisper-base',
        'small': 'openai/whisper-small',
        'medium': 'openai/whisper-medium',
        'large': 'openai/whisper-large-v3',
        'large-v1': 'openai/whisper-large-v1',
        'large-v2': 'openai/whisper-large-v2',
        'large-v3': 'openai/whisper-large-v3',
        'large-v3-turbo': 'openai/whisper-large-v3-turbo'
    }

    model_id = model_mapping.get(WHISPER_MODEL_SIZE, 'openai/whisper-large-v3')

    speech_recognition_pipeline = pipeline(
        "automatic-speech-recognition",
        model=model_id,
        torch_dtype=torch.float16 if device.startswith("cuda") else torch.float32,
        device=device,
    )
    logger.info(f"Model {model_id} loaded on {device}")
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
    language = request.form.get('language', 'en')

    # Get additional transcription parameters
    timestamps = request.form.get('timestamps', 'false').lower() == 'true'
    initial_prompt = request.form.get('initial_prompt', '')
    temperature = float(request.form.get('temperature', '0.0'))
    beam_size = int(request.form.get('beam_size', '5'))
    return_segments = request.form.get('return_segments', 'false').lower() == 'true'

    # Save file temporarily with appropriate format
    temp_path = f"{TEMP_FILE_PREFIX}_{os.getpid()}.{AUDIO_FORMAT}"
    audio_file.save(temp_path)

    try:
        # Process with Whisper model
        generate_kwargs = {
            "language": language,
            "task": "transcribe",
            "beam_size": beam_size,
        }

        if initial_prompt:
            generate_kwargs["prompt"] = initial_prompt

        if temperature > 0:
            generate_kwargs["temperature"] = temperature

        result = pipe(
            temp_path,
            chunk_length_s=WHISPER_CHUNK_LENGTH,
            batch_size=WHISPER_BATCH_SIZE,
            return_timestamps=timestamps,
            generate_kwargs=generate_kwargs
        )

        # Format response based on what was requested
        if return_segments and hasattr(result, 'chunks'):
            response = {"text": result["text"], "segments": result["chunks"]}
        else:
            response = {"text": result["text"]}

        return jsonify(response)
    except Exception as e:
        logger.error(f"Transcription error: {str(e)}")
        return jsonify({"error": "Transcription failed", "details": str(e)}), 500
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
    # Ensure required packages are installed
    required_packages = ['flask', 'torch', 'transformers', 'python-dotenv']
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            logger.info(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

    # Run the Flask application
    app.run(host=WHISPER_SERVER_HOST, port=WHISPER_SERVER_PORT, timeout=SERVER_TIMEOUT)
