#!/usr/bin/env python3
import sys
import os
import time
import subprocess
import signal

def is_server_running():
    """Check if the Whisper server is already running."""
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
                # Also verify server responds to health check
                import requests
                try:
                    response = requests.get('http://127.0.0.1:5000/health', timeout=2)
                    if response.status_code == 200:
                        return True
                except:
                    # If health check fails, continue with other checks
                    pass
    except (ValueError, FileNotFoundError, IOError):
        pass

    # Clean up obsolete PID file
    try:
        os.remove(pid_file)
    except:
        pass

    return False

def start_server_daemon():
    """Start the Whisper server as a daemon process."""
    print("Starting Whisper server with large-v3-turbo model in daemon mode...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    server_path = os.path.join(script_dir, "whisper_server.py")
    venv_dir = os.path.expanduser("~/virtualenvs/whisper-env")
    python_path = os.path.join(venv_dir, "bin", "python")

    # Ensure the file has execution permissions
    os.chmod(server_path, 0o755)

    # Log file for server output
    log_file = os.path.expanduser("~/whisper_server.log")

    # Start the server as a daemon process
    with open(log_file, "a") as log:
        process = subprocess.Popen(
            [python_path, server_path],
            stdout=log,
            stderr=log,
            close_fds=True
        )

    # Wait for server to start
    print("Server starting in background. Waiting for it to be ready...")
    start_time = time.time()
    while time.time() - start_time < 300:  # 5 minutes timeout
        if is_server_running():
            print(f"Server started successfully. Log available at {log_file}")
            return True
        time.sleep(2)

    print("Timeout waiting for server to start")
    return False

def transcribe_audio(audio_file, language="en"):
    """Transcribe audio using the Whisper server."""
    # Import requests from the virtual environment
    venv_dir = os.path.expanduser("~/virtualenvs/whisper-env")
    sys.path.insert(0, os.path.join(venv_dir, "lib", "python3.12", "site-packages"))
    try:
        import requests
    except ImportError:
        print("Error: requests module not found in virtual environment")
        return None

    # Make sure the server is running
    if not is_server_running():
        if not start_server_daemon():
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
    language = sys.argv[2] if len(sys.argv) > 2 else "en"

    # Transcribe
    result = transcribe_audio(audio_file, language)
    if result:
        print("Transcription complete")
    else:
        print("Transcription failed")
