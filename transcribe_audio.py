#!/usr/bin/env python3
import sys
import os
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
    print("Starting Whisper server with large-v3-turbo model...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    server_path = os.path.join(script_dir, "whisper_server.py")
    venv_dir = os.path.expanduser("~/virtualenvs/whisper-env")
    python_path = os.path.join(venv_dir, "bin", "python")

    # Ensure the file has execution permissions
    os.chmod(server_path, 0o755)

    # Start the server in the foreground to see output, but redirect to both terminal and log
    log_file = os.path.expanduser("~/whisper_server.log")
    print(f"Server logs will be saved to {log_file}")

    # Use tee to show output in terminal and save to file
    process = subprocess.Popen(
        [python_path, server_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    # Create a separate process to display logs in real-time
    with open(log_file, "w") as f:
        print("Waiting for server to initialize (this may take several minutes on first run)...")
        print("The model is very large (~10GB) and needs to be downloaded and loaded...")

        # Wait until the server is ready (with increased timeout)
        start_time = time.time()
        while time.time() - start_time < 900:  # 15 minutes timeout
            try:
                # Read and display output in real-time
                line = process.stdout.readline()
                if line:
                    print(f"Server: {line.strip()}")
                    f.write(line)
                    f.flush()

                    # If we see the model loaded message, we can proceed
                    if "Model loaded successfully" in line:
                        print("Model loaded successfully, waiting for server to be ready...")
                        time.sleep(10)  # Give time for Flask to start

                # Check if the server is responding via PID file
                if os.path.exists(os.path.expanduser("~/.whisper_server.pid")):
                    try:
                        with open(os.path.expanduser("~/.whisper_server.pid"), "r") as pid_file:
                            pid = int(pid_file.read().strip())
                            # Verify the process exists
                            os.kill(pid, 0)  # This will raise an exception if the process doesn't exist
                            print(f"Server started successfully with PID {pid}")
                            return True
                    except (ValueError, ProcessLookupError):
                        # PID file exists but process doesn't
                        pass

                # Check if the process is still running
                if process.poll() is not None:
                    print(f"Server process terminated with exit code {process.returncode}")
                    # Get any remaining output
                    remaining_output = process.stdout.read()
                    if remaining_output:
                        print(f"Final output: {remaining_output}")
                    return False

                time.sleep(1)
            except KeyboardInterrupt:
                print("Server startup canceled by user")
                process.terminate()
                return False

        print("Error: Timeout waiting for server to start")
        # Try to terminate the process if it's still running
        process.terminate()
        return False

def transcribe_audio(audio_file, language="es"):
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

    # Transcribe
    result = transcribe_audio(audio_file, language)
    if result:
        print("Transcription complete")
    else:
        print("Transcription failed")
