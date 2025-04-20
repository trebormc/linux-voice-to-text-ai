#!/usr/bin/env python3
import os
import sys
import time
import subprocess
import signal
import psutil

# Constants
SERVER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper_server.py")
PID_FILE = os.path.expanduser("~/.whisper_server.pid")

def is_server_running():
    """Check if server is already running"""
    if not os.path.exists(PID_FILE):
        return False

    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())

        process = psutil.Process(pid)
        if "whisper_server.py" in " ".join(process.cmdline()):
            return True
    except (FileNotFoundError, ValueError, psutil.NoSuchProcess):
        pass

    # Clean up stale PID file
    try:
        os.remove(PID_FILE)
    except:
        pass

    return False

def start_server():
    """Start the Whisper server if not already running"""
    if is_server_running():
        print("Whisper server is already running")
        return True

    # Make sure script is executable
    os.chmod(SERVER_SCRIPT, 0o755)

    # Start the server in a new process
    print("Starting whisper server...")
    subprocess.Popen(
        [sys.executable, SERVER_SCRIPT],
        start_new_session=True,
        stdout=open(os.devnull, 'w'),
        stderr=open(os.path.expanduser("~/whisper_server_error.log"), 'w')
    )

    # Wait for server to start
    max_wait = 120  # seconds
    for i in range(max_wait):
        if is_server_running():
            # Check if server is actually accepting connections
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', 5000))
            sock.close()

            if result == 0:
                print(f"Server started successfully after {i+1} seconds")
                return True

        time.sleep(1)
        if i % 10 == 0:
            print(f"Waiting for server to initialize... ({i} seconds)")

    print("Error: Timeout waiting for server to start")
    return False

if __name__ == "__main__":
    try:
        import psutil
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil"])
        import psutil

    start_server()
