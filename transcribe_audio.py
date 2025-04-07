#!/usr/bin/env python3
import sys
import os
import requests
import time
import subprocess
import signal

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

def transcribe_audio(audio_file, language="es"):
    # Make sure the server is running
    if not is_server_running():
        if not start_server():
            print("Failed to start the transcription server")
            return None

    print("Sending audio to transcription service...")
    try:
        with open(audio_file, 'rb') as f:
            files = {'file': f}
            data = {'language': language}
            response = requests.post('http://127.0.0.1:5000/transcribe',
                                    files=files,
                                    data=data,
                                    timeout=180)  # 3 minutes timeout

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

    audio_file = sys.argv[1]
    language = sys.argv[2] if len(sys.argv) > 2 else "es"

    # Install requests if not available
    try:
        import requests
    except ImportError:
        print("Installing required dependency: requests")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        import requests

    # Transcribe
    result = transcribe_audio(audio_file, language)
    if result:
        print("Transcription complete")
    else:
        print("Transcription failed")
