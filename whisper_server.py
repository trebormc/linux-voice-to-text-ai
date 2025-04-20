#!/usr/bin/env python3
import torch
from transformers import pipeline
from flask import Flask, request, jsonify
import os
import signal
import sys
import subprocess
import logging
import time
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.expanduser("~/whisper_server.log"))
    ]
)
logger = logging.getLogger(__name__)

# Path constants
PID_FILE_PATH = os.path.expanduser("~/.whisper_server.pid")
TEMP_FILE_PREFIX = "/tmp/whisper_temp"

# Global variables
app = Flask(__name__)
pipe = None

def load_environment():
    """Load environment variables from .env file"""
    try:
        import dotenv
        script_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(script_dir, '.env')
        if os.path.exists(env_path):
            dotenv.load_dotenv(dotenv_path=env_path)
            logger.info(f"Loaded environment from {env_path}")
    except ImportError:
        logger.warning("python-dotenv not installed, skipping .env file loading")

    # Set defaults if not defined
    os.environ.setdefault('WHISPER_MODEL_SIZE', 'large-v3')
    os.environ.setdefault('WHISPER_DEVICE', 'auto')
    os.environ.setdefault('WHISPER_CPU_THREADS', '4')
    os.environ.setdefault('WHISPER_BATCH_SIZE', '24')
    os.environ.setdefault('WHISPER_CHUNK_LENGTH', '15')
    os.environ.setdefault('WHISPER_SERVER_HOST', '127.0.0.1')
    os.environ.setdefault('WHISPER_SERVER_PORT', '5000')
    os.environ.setdefault('SERVER_TIMEOUT', '180')
    os.environ.setdefault('AUDIO_FORMAT', 'flac')

def install_dependencies():
    """Install required dependencies if missing"""
    logger.info("Checking dependencies...")
    required_packages = ['torch', 'transformers', 'flask', 'python-dotenv']
    for package in required_packages:
        try:
            __import__(package.replace('-', '_'))
        except ImportError:
            logger.info(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

def initialize_model():
    """Initialize and load the speech recognition model."""
    # Get configuration from environment variables
    model_size = os.environ.get('WHISPER_MODEL_SIZE', 'large-v3')
    device_setting = os.environ.get('WHISPER_DEVICE', 'auto')
    cpu_threads = int(os.environ.get('WHISPER_CPU_THREADS', '4'))

    logger.info(f"Loading Whisper model: {model_size}...")

    # Determine device
    if device_setting == 'auto':
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    elif device_setting == 'cuda':
        device = "cuda:0"
    else:
        device = "cpu"

    # Set thread count for CPU computations
    if device == "cpu":
        torch.set_num_threads(cpu_threads)
        logger.info(f"Set CPU threads to {cpu_threads}")

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
    }

    model_id = model_mapping.get(model_size, 'openai/whisper-large-v3')

    try:
        speech_recognition_pipeline = pipeline(
            "automatic-speech-recognition",
            model=model_id,
            torch_dtype=torch.float16 if device.startswith("cuda") else torch.float32,
            device=device,
        )
        logger.info(f"Model {model_id} loaded successfully on {device}")
        return speech_recognition_pipeline
    except Exception as e:
        logger.error(f"Error loading model: {str(e)}")
        raise

@app.route('/transcribe', methods=['POST'])
def transcribe():
    """Transcribe audio file using Whisper model."""
    global pipe
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
    audio_format = os.environ.get('AUDIO_FORMAT', 'flac')
    temp_path = f"{TEMP_FILE_PREFIX}_{os.getpid()}.{audio_format}"
    audio_file.save(temp_path)

    try:
        # Process with Whisper model
        generate_kwargs = {
            "language": language,
            "task": "transcribe",
            "num_beams": beam_size,
        }

        if initial_prompt:
            generate_kwargs["prompt"] = initial_prompt

        if temperature > 0:
            generate_kwargs["temperature"] = temperature

        batch_size = int(os.environ.get('WHISPER_BATCH_SIZE', '24'))
        chunk_length = int(os.environ.get('WHISPER_CHUNK_LENGTH', '15'))

        logger.info(f"Transcribing audio file with language={language}, chunk_length={chunk_length}, batch_size={batch_size}")

        result = pipe(
            temp_path,
            chunk_length_s=chunk_length,
            batch_size=batch_size,
            return_timestamps=timestamps,
            generate_kwargs=generate_kwargs
        )

        # Format response based on what was requested
        if return_segments and "chunks" in result:
            response = {"text": result["text"], "segments": result["chunks"]}
        else:
            response = {"text": result["text"]}

        logger.info(f"Transcription completed successfully")
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
    sys.exit(0)

if __name__ == '__main__':
    # Load environment and install dependencies
    load_environment()
    install_dependencies()

    # Save PID for other processes to detect server
    with open(PID_FILE_PATH, "w") as pid_file:
        pid_file.write(str(os.getpid()))

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Initialize the model
    pipe = initialize_model()

    # Get host and port from environment
    host = os.environ.get('WHISPER_SERVER_HOST', '127.0.0.1')
    port = int(os.environ.get('WHISPER_SERVER_PORT', '5000'))

    logger.info(f"Starting Flask server on {host}:{port}")
    app.run(host=host, port=port, debug=False)
