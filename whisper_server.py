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
import argparse
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
    if not os.environ.get('WHISPER_MODEL_SIZE'):
        os.environ['WHISPER_MODEL_SIZE'] = 'large-v3'
    if not os.environ.get('WHISPER_DEVICE'):
        os.environ['WHISPER_DEVICE'] = 'auto'
    if not os.environ.get('WHISPER_CPU_THREADS'):
        os.environ['WHISPER_CPU_THREADS'] = '4'
    if not os.environ.get('WHISPER_BATCH_SIZE'):
        os.environ['WHISPER_BATCH_SIZE'] = '24'
    if not os.environ.get('WHISPER_CHUNK_LENGTH'):
        os.environ['WHISPER_CHUNK_LENGTH'] = '15'
    if not os.environ.get('WHISPER_SERVER_HOST'):
        os.environ['WHISPER_SERVER_HOST'] = '127.0.0.1'
    if not os.environ.get('WHISPER_SERVER_PORT'):
        os.environ['WHISPER_SERVER_PORT'] = '5000'
    if not os.environ.get('SERVER_TIMEOUT'):
        os.environ['SERVER_TIMEOUT'] = '180'
    if not os.environ.get('AUDIO_FORMAT'):
        os.environ['AUDIO_FORMAT'] = 'flac'

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

def is_server_running():
    """Check if the server is already running"""
    if not os.path.exists(PID_FILE_PATH):
        return False

    try:
        with open(PID_FILE_PATH, "r") as f:
            pid = int(f.read().strip())

        # Check if process exists and is a whisper server
        os.kill(pid, 0)  # This will raise an exception if process doesn't exist

        # On Linux, we can check the process name
        if os.path.exists(f"/proc/{pid}/cmdline"):
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmdline = f.read().decode('utf-8', errors='ignore')
                if "whisper_server.py" in cmdline:
                    return True

        # If we're here, PID exists but might not be our server
        logger.warning(f"Process {pid} exists but might not be whisper server")
        return True
    except (ProcessLookupError, FileNotFoundError, ValueError):
        # Process doesn't exist or PID file is invalid
        logger.info("Removing stale PID file")
        try:
            os.remove(PID_FILE_PATH)
        except:
            pass
        return False

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
        'large-v3-turbo': 'openai/whisper-large-v3-turbo'
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

def start_server(foreground=False):
    """Start the server process"""
    if is_server_running():
        logger.info("Whisper server is already running")
        return True

    logger.info("Starting Whisper server...")

    if foreground:
        # Run in foreground
        run_server()
    else:
        # Start in background
        cmd = [sys.executable, __file__, "--run"]
        logger.info(f"Launching background process: {' '.join(cmd)}")
        with open(os.devnull, 'w') as devnull:
            subprocess.Popen(
                cmd,
                stdout=devnull,
                stderr=devnull,
                start_new_session=True
            )

        # Wait for server to start
        logger.info("Waiting for server to start...")
        start_time = time.time()
        while time.time() - start_time < 120:  # 2 minute timeout
            if is_server_running():
                logger.info("Server started successfully")
                return True
            time.sleep(1)

        logger.error("Timeout waiting for server to start")
        return False

def stop_server():
    """Stop the whisper server if running"""
    if not os.path.exists(PID_FILE_PATH):
        logger.info("No server is running")
        return

    try:
        with open(PID_FILE_PATH, "r") as f:
            pid = int(f.read().strip())

        logger.info(f"Stopping server with PID {pid}")
        os.kill(pid, signal.SIGTERM)

        # Wait for the process to terminate
        max_wait = 30
        for _ in range(max_wait):
            try:
                os.kill(pid, 0)  # Check if process exists
                time.sleep(1)
            except OSError:
                break

        # If process is still running, force kill
        try:
            os.kill(pid, 0)
            logger.warning(f"Server didn't terminate gracefully, sending SIGKILL")
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

        # Remove PID file
        if os.path.exists(PID_FILE_PATH):
            os.remove(PID_FILE_PATH)

        logger.info("Server stopped successfully")
    except Exception as e:
        logger.error(f"Error stopping server: {str(e)}")

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
    audio_format = os.environ.get('AUDIO_FORMAT', 'flac')
    temp_path = f"{TEMP_FILE_PREFIX}_{os.getpid()}.{audio_format}"
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

def run_server():
    """Run the Flask server"""
    global pipe

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
    timeout = int(os.environ.get('SERVER_TIMEOUT', '180'))

    logger.info(f"Starting Flask server on {host}:{port}")
    # We use threaded=True for better concurrency
    app.run(host=host, port=port, threaded=True, timeout=timeout)

def main():
    """Main entry point with command line argument parsing"""
    parser = argparse.ArgumentParser(description="Whisper Server for Speech Transcription")
    parser.add_argument("--run", action="store_true", help="Run the server in foreground")
    parser.add_argument("--stop", action="store_true", help="Stop the running server")
    parser.add_argument("--restart", action="store_true", help="Restart the server")
    parser.add_argument("--status", action="store_true", help="Check server status")

    args = parser.parse_args()

    # Load environment variables and install dependencies
    load_environment()
    install_dependencies()

    if args.stop or args.restart:
        stop_server()
        if args.stop:
            return

    if args.status:
        if is_server_running():
            with open(PID_FILE_PATH, "r") as f:
                pid = f.read().strip()
            print(f"Whisper server is running with PID {pid}")
        else:
            print("Whisper server is not running")
        return

    if args.run:
        run_server()
    else:
        start_server(foreground=False)

if __name__ == '__main__':
    main()
