#!/usr/bin/env python3
import os
import sys
import time
import signal
import subprocess
import threading
import requests
import dotenv
from pathlib import Path
import logging

# Configure logging for debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Determine script directory and load environment variables
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = SCRIPT_DIR / ".env"
dotenv.load_dotenv(ENV_FILE)

# Configuration from environment variables
ENABLE_LOCAL_WHISPER = os.getenv("ENABLE_LOCAL_WHISPER", "false").lower() == "true"
TRANSCRIPTION_LANGUAGE = os.getenv("TRANSCRIPTION_LANGUAGE", "en")
AUDIO_INPUT = os.getenv("AUDIO_INPUT", "@DEFAULT_SOURCE@")
MAX_DURATION = int(os.getenv("MAX_DURATION", "120"))
OPEN_AI_TOKEN = os.getenv("OPEN_AI_TOKEN", "")
DEEPGRAM_TOKEN = os.getenv("DEEPGRAM_TOKEN", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "whisper-1")
DEEPGRAM_PARAMS = os.getenv("DEEPGRAM_PARAMS", "smart_format=true&paragraphs=true&punctuate=true&model=nova-2")
SOUND_START_RECORDING = os.getenv("SOUND_START_RECORDING", "/usr/share/sounds/freedesktop/stereo/service-login.oga")
SOUND_STOP_RECORDING = os.getenv("SOUND_STOP_RECORDING", "/usr/share/sounds/freedesktop/stereo/service-logout.oga")
SOUND_END_TRANSCRIPTION = os.getenv("SOUND_END_TRANSCRIPTION", "/usr/share/sounds/freedesktop/stereo/audio-volume-change.oga")

# Constants and directories
HOME_DIR = os.path.expanduser("~")
VOICE_TO_TEXT_DIR = f"{HOME_DIR}/.voice-to-text"
RECORDING_FILE = f"{VOICE_TO_TEXT_DIR}/recording"
AUDIO_FORMAT = "wav"
WHISPER_SERVER_URL = "http://127.0.0.1:5000"

# Global variables
recording_process = None
recording_active = False
full_transcription = ""
stop_event = threading.Event()

# Prepare directories
os.makedirs(VOICE_TO_TEXT_DIR, exist_ok=True)

def play_sound(sound_path):
    """Plays a sound using paplay"""
    if os.path.exists(sound_path):
        try:
            subprocess.run(["paplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.error(f"Error playing sound: {e}")

def copy_to_clipboard(text):
    """Copies text to clipboard using xclip or wl-copy"""
    try:
        # Try with xclip first
        process = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
        process.communicate(input=text.encode())
        if process.returncode == 0:
            return True

        # If xclip fails, try with wl-copy
        process = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
        process.communicate(input=text.encode())
        return process.returncode == 0
    except:
        try:
            # Last resort: try wl-copy
            process = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
            process.communicate(input=text.encode())
            return process.returncode == 0
        except:
            logger.error("Could not copy to clipboard. Install xclip or wl-copy.")
            return False

def paste_clipboard():
    """Simulates pressing Ctrl+V using xdotool"""
    try:
        time.sleep(0.2)  # small pause to ensure clipboard is ready
        subprocess.run(["xdotool", "key", "ctrl+v"], check=True)
        return True
    except:
        logger.error("Could not paste. Make sure xdotool is installed.")
        return False

def check_whisper_server():
    """Checks if the Whisper server is running"""
    try:
        response = requests.get(f"{WHISPER_SERVER_URL}/health", timeout=2)
        return response.status_code == 200
    except:
        return False

def transcribe_with_whisper(audio_file):
    """Transcribes using the local Whisper server"""
    if not os.path.exists(audio_file) or os.path.getsize(audio_file) == 0:
        return ""

    try:
        with open(audio_file, 'rb') as f:
            files = {'file': f}
            data = {'language': TRANSCRIPTION_LANGUAGE}
            response = requests.post(
                f"{WHISPER_SERVER_URL}/transcribe",
                files=files,
                data=data,
                timeout=30
            )

        if response.status_code == 200:
            return response.json().get("text", "")
        else:
            logger.error(f"Error in transcription: {response.status_code}")
            return ""
    except Exception as e:
        logger.error(f"Error transcribing with Whisper: {e}")
        return ""

def transcribe_with_deepgram(audio_file):
    """Transcribes using the Deepgram API"""
    if not DEEPGRAM_TOKEN or not os.path.exists(audio_file) or os.path.getsize(audio_file) == 0:
        return ""

    try:
        url = f"https://api.deepgram.com/v1/listen?{DEEPGRAM_PARAMS}&language={TRANSCRIPTION_LANGUAGE}"

        with open(audio_file, 'rb') as f:
            headers = {
                "Authorization": f"Token {DEEPGRAM_TOKEN}",
                "Content-Type": f"audio/{AUDIO_FORMAT}"
            }
            response = requests.post(url, headers=headers, data=f, timeout=30)

        if response.status_code == 200:
            result = response.json()
            return result["results"]["channels"][0]["alternatives"][0]["transcript"]
        else:
            logger.error(f"Error in Deepgram transcription: {response.status_code}")
            return ""
    except Exception as e:
        logger.error(f"Error transcribing with Deepgram: {e}")
        return ""

def transcribe_with_openai(audio_file):
    """Transcribes using the OpenAI API"""
    if not OPEN_AI_TOKEN or not os.path.exists(audio_file) or os.path.getsize(audio_file) == 0:
        return ""

    try:
        url = "https://api.openai.com/v1/audio/transcriptions"

        with open(audio_file, 'rb') as f:
            headers = {
                "Authorization": f"Bearer {OPEN_AI_TOKEN}"
            }
            files = {
                "file": f
            }
            data = {
                "model": OPENAI_MODEL,
                "response_format": "text",
                "temperature": 0.0,
                "language": TRANSCRIPTION_LANGUAGE
            }
            response = requests.post(url, headers=headers, files=files, data=data, timeout=30)

        if response.status_code == 200:
            return response.text.strip()
        else:
            logger.error(f"Error in OpenAI transcription: {response.status_code}")
            return ""
    except Exception as e:
        logger.error(f"Error transcribing with OpenAI: {e}")
        return ""

def start_recording():
    """Starts audio recording"""
    global recording_process, recording_active

    # File for recording
    audio_file = f"{RECORDING_FILE}.{AUDIO_FORMAT}"

    # Clean previous recording if exists
    if os.path.exists(audio_file):
        try:
            os.remove(audio_file)
        except:
            pass

    # Command to record directly in WAV for better compatibility
    cmd = [
        "parecord",
        "--channels=1",
        "--format=s16le",
        "--rate=16000",
        "--file-format=wav",
        "--device", AUDIO_INPUT,
        audio_file
    ]

    try:
        # Start recording process
        recording_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        recording_active = True
        return audio_file
    except Exception as e:
        logger.error(f"Error starting recording: {e}")

        # Try with default device
        try:
            cmd[6] = "@DEFAULT_SOURCE@"  # Change to default device
            recording_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            recording_active = True
            return audio_file
        except Exception as e:
            logger.error(f"Error starting recording with default device: {e}")
            recording_active = False
            return None

def stop_recording():
    time.sleep(0.5)
    """Stops audio recording"""
    global recording_process, recording_active

    if recording_process and recording_active:
        try:
            # Send SIGTERM and give more time for proper cleanup
            recording_process.terminate()
            # Wait longer to ensure the audio file is properly closed
            recording_process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            logger.warning("Recording process taking too long to terminate, forcing kill")
            try:
                recording_process.kill()
                recording_process.wait(timeout=2)
            except:
                logger.error("Failed to kill recording process")
        except Exception as e:
            logger.error(f"Error stopping recording: {e}")
            try:
                recording_process.kill()
            except:
                pass

    recording_active = False

def handle_exit(signal, frame):
    """Handles interrupt signal"""
    print("\nInterrupting transcription...")
    stop_event.set()
    stop_recording()
    sys.exit(0)

def wait_for_keypress():
    """Waits until the user presses a key to stop recording"""
    print("Recording... Press any key to stop.")
    try:
        import termios, fcntl, sys, os
        fd = sys.stdin.fileno()

        # Save current settings
        old_settings = termios.tcgetattr(fd)

        # Set up for non-blocking read
        new_settings = termios.tcgetattr(fd)
        new_settings[3] = new_settings[3] & ~termios.ICANON & ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, new_settings)

        # Set non-blocking mode
        old_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)

        try:
            while recording_active and not stop_event.is_set():
                try:
                    c = sys.stdin.read(1)
                    if c:
                        return
                except IOError:
                    pass
                time.sleep(0.1)
        finally:
            # Restore settings
            termios.tcsetattr(fd, termios.TCSAFLUSH, old_settings)
            fcntl.fcntl(fd, fcntl.F_SETFL, old_flags)
    except:
        # Simple fallback
        input()

def main():
    global recording_active, full_transcription

    # Register signal handler for Ctrl+C
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # Check dependencies
    whisper_server_available = False
    if ENABLE_LOCAL_WHISPER:
        whisper_server_available = check_whisper_server()
        if not whisper_server_available:
            print("Error: Whisper server is not available. Run ensure_whisper_server first.")
            return 1

    # Check if any transcription service is configured
    if not ENABLE_LOCAL_WHISPER and not OPEN_AI_TOKEN and not DEEPGRAM_TOKEN:
        print("Error: No transcription service configured.")
        print("Set ENABLE_LOCAL_WHISPER=true or provide OPEN_AI_TOKEN or DEEPGRAM_TOKEN in the .env file")
        return 1

    print(f"Transcription configured with:")
    print(f"- Local Whisper: {'Enabled' if ENABLE_LOCAL_WHISPER else 'Disabled'}")
    print(f"- OpenAI API: {'Configured' if OPEN_AI_TOKEN else 'Not configured'}")
    print(f"- Deepgram API: {'Configured' if DEEPGRAM_TOKEN else 'Not configured'}")
    print(f"- Language: {TRANSCRIPTION_LANGUAGE}")

    # Start recording
    audio_file = start_recording()
    if not audio_file:
        logger.error("Could not start recording")
        return 1

    # Small pause to ensure recording has started
    time.sleep(0.3)

    # Play start sound JUST BEFORE starting recording
    play_sound(SOUND_START_RECORDING)

    # Wait for user to stop recording
    wait_for_keypress()

    # Stop recording
    stop_recording()

    # Play stop sound
    play_sound(SOUND_STOP_RECORDING)

    print("\nProcessing the audio file...")

    # Process the complete audio file
    if ENABLE_LOCAL_WHISPER and whisper_server_available:
        print("Using local Whisper for transcription...")
        full_transcription = transcribe_with_whisper(audio_file)
    elif DEEPGRAM_TOKEN:
        print("Using Deepgram API for transcription...")
        full_transcription = transcribe_with_deepgram(audio_file)
    elif OPEN_AI_TOKEN:
        print("Using OpenAI API for transcription...")
        full_transcription = transcribe_with_openai(audio_file)

    # Show final result
    print("\nFinal Transcription:")
    print("-" * 50)
    print(full_transcription)
    print("-" * 50)

    # Save to file
    with open(f"{RECORDING_FILE}.txt", "w") as f:
        f.write(full_transcription)

    # Copy to clipboard
    if copy_to_clipboard(full_transcription):
        print("Transcription copied to clipboard")

        # Paste automatically
        if paste_clipboard():
            print("Transcription automatically pasted")

        # Play end sound AFTER copying and pasting the text
        play_sound(SOUND_END_TRANSCRIPTION)

    return 0

if __name__ == "__main__":
    sys.exit(main())
