#!/usr/bin/env python3
import sys
import os
import requests
import time
import subprocess
import signal
import dotenv
from pathlib import Path

def load_env():
    """Load environment variables from .env file"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(script_dir, '.env')
    if os.path.exists(env_path):
        dotenv.load_dotenv(env_path)

    # Set default values if not defined in .env
    if not os.environ.get('WHISPER_SERVER_HOST'):
        os.environ['WHISPER_SERVER_HOST'] = '127.0.0.1'
    if not os.environ.get('WHISPER_SERVER_PORT'):
        os.environ['WHISPER_SERVER_PORT'] = '5000'
    if not os.environ.get('SERVER_TIMEOUT'):
        os.environ['SERVER_TIMEOUT'] = '180'
    if not os.environ.get('TRANSCRIPTION_LANGUAGE'):
        os.environ['TRANSCRIPTION_LANGUAGE'] = 'es'

def is_server_running():
    # Check if PID file exists
    pid_file = os.path.expanduser("~/.whisper_server.pid")
    if not os.path.exists(pid_file):
        return False

    # Read PID and verify if that process is running
    try:
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())

        # Check if the process exists
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read().decode('utf-8', errors='ignore')
            if "whisper_server.py" in cmdline:
                return True
    except (ValueError, FileNotFoundError, IOError):
        pass

    # Clean up obsolete PID file
    try:
        os.remove(pid_file)
    except:
        pass

    return False

def start_server():
    print("Starting Whisper server...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    server_path = os.path.join(script_dir, "whisper_server.py")

    # Ensure the file has execution permissions
    os.chmod(server_path, 0o755)

    # Install necessary dependencies
    try:
        import flask
    except ImportError:
        print("Installing Flask...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])

    try:
        import dotenv
    except ImportError:
        print("Installing python-dotenv...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "python-dotenv"])

    # Start the server in the background
    subprocess.Popen(
        [sys.executable, server_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True
    )

    # Wait until the server is ready (with timeout)
    start_time = time.time()
    while time.time() - start_time < 120:  # 2 minutes timeout
        try:
            # Check if the server is responding
            if os.path.exists(os.path.expanduser("~/.whisper_server.pid")):
                time.sleep(5)  # Give time for the model to fully load
                return True
        except:
            pass
        time.sleep(1)

    print("Error: Timeout waiting for server to start")
    return False

def transcribe_audio(audio_file, language=None):
    # Load environment variables
    load_env()

    # Use environment variables or defaults
    host = os.environ.get('WHISPER_SERVER_HOST', '127.0.0.1')
    port = os.environ.get('WHISPER_SERVER_PORT', '5000')
    timeout = int(os.environ.get('SERVER_TIMEOUT', 180))
    if language is None:
        language = os.environ.get('TRANSCRIPTION_LANGUAGE', 'es')

    # Make sure the server is running
    if not is_server_running():
        if not start_server():
            print("Failed to start the transcription server")
            return None

    print(f"Sending audio to transcription service at {host}:{port}...")
    try:
        with open(audio_file, 'rb') as f:
            files = {'file': f}

            # Prepare all transcription parameters
            data = {
                'language': language,
                'timestamps': os.environ.get('TRANSCRIPTION_TIMESTAMPS', 'false'),
                'diarization': os.environ.get('TRANSCRIPTION_DIARIZATION', 'false'),
                'return_segments': os.environ.get('TRANSCRIPTION_RETURN_SEGMENTS', 'false'),
                'initial_prompt': os.environ.get('TRANSCRIPTION_INITIAL_PROMPT', ''),
                'temperature': os.environ.get('TRANSCRIPTION_TEMPERATURE', '0.0'),
                'beam_size': os.environ.get('TRANSCRIPTION_BEAM_SIZE', '5')
            }

            response = requests.post(
                f'http://{host}:{port}/transcribe',
                files=files,
                data=data,
                timeout=timeout
            )

        if response.status_code == 200:
            result = response.json()
            output_file = audio_file.replace("." + audio_file.split(".")[-1], ".txt")
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(result["text"])

            return result["text"]
        else:
            print(f"Error: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Connection error: {e}")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python transcribe_audio.py <audio_file> [language]")
        sys.exit(1)

    # Install required dependencies
    required_packages = ["requests", "python-dotenv"]
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            print(f"Installing required dependency: {package}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

    import requests
    import dotenv

    audio_file = sys.argv[1]
    language = sys.argv[2] if len(sys.argv) > 2 else None  # Use default from .env if not specified

    # Transcribe
    result = transcribe_audio(audio_file, language)
    if result:
        print("Transcription complete")
    else:
        print("Transcription failed")
