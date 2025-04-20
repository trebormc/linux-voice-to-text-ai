#!/usr/bin/env python3
import os
import sys
import time
import subprocess
import dotenv
from pathlib import Path
import logging
import torch
from faster_whisper import WhisperModel

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Determine script directory and load environment variables
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = SCRIPT_DIR / ".env"
dotenv.load_dotenv(ENV_FILE)

# Configuration from environment variables
TRANSCRIPTION_LANGUAGE = os.getenv("TRANSCRIPTION_LANGUAGE", "en")
AUDIO_INPUT = os.getenv("AUDIO_INPUT", "@DEFAULT_SOURCE@")
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "medium")
WHISPER_CPU_THREADS = int(os.getenv("WHISPER_CPU_THREADS", "4"))
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
PID_FILE = f"{VOICE_TO_TEXT_DIR}/recording.pid"
RECORDING_FILE = f"{VOICE_TO_TEXT_DIR}/recording.wav"
AUDIO_FORMAT = "wav"

# Prepare directories
os.makedirs(VOICE_TO_TEXT_DIR, exist_ok=True)

def play_sound(sound_path, async_play=False):
    """Plays a sound using paplay, optionally asynchronously"""
    if not os.path.exists(sound_path):
        return None

    cmd = ["paplay", sound_path]
    try:
        if async_play:
            return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return None
    except Exception as e:
        logger.error(f"Error playing sound: {e}")
        return None

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

def transcribe_with_faster_whisper(audio_file):
    """Transcribes using the Faster Whisper model"""
    if not os.path.exists(audio_file) or os.path.getsize(audio_file) == 0:
        logger.error("Audio file is empty or doesn't exist")
        return ""

    try:
        print(f"Loading Whisper model {WHISPER_MODEL_SIZE}...")
        # Initialize Whisper model with optimal settings
        model = WhisperModel(
            WHISPER_MODEL_SIZE,
            device="cuda" if torch.cuda.is_available() else "cpu",
            compute_type="int8" if not torch.cuda.is_available() else "float16",
            cpu_threads=WHISPER_CPU_THREADS,
            download_root=f"{VOICE_TO_TEXT_DIR}/models"
        )

        device_type = "GPU" if torch.cuda.is_available() else f"CPU ({WHISPER_CPU_THREADS} threads)"
        print(f"Transcribing with {WHISPER_MODEL_SIZE} model on {device_type}")

        segments, info = model.transcribe(
            audio_file,
            language=TRANSCRIPTION_LANGUAGE,
            beam_size=3,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
            word_timestamps=False
        )

        # Collect all segment texts
        result = " ".join([segment.text for segment in segments])
        print(f"Transcription complete: {len(result)} characters")
        return result
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
    """Starts audio recording and returns the process"""
    # Clean previous recording if exists
    if os.path.exists(RECORDING_FILE):
        try:
            os.remove(RECORDING_FILE)
        except Exception as e:
            logger.error(f"Could not remove existing recording file: {e}")

    # Command to record directly in WAV format
    cmd = [
        "parecord",
        "--channels=1",
        "--format=s16le",
        "--rate=16000",
        "--file-format=wav",
        "--device", AUDIO_INPUT,
        RECORDING_FILE
    ]

    try:
        # Start recording process
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Write PID file
        with open(PID_FILE, 'w') as f:
            f.write(str(proc.pid))

        # Give it a moment to start
        time.sleep(0.2)

        return proc
    except Exception as e:
        logger.error(f"Error starting recording: {e}")

        try:
            # Try with default device
            cmd[6] = "@DEFAULT_SOURCE@"
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            with open(PID_FILE, 'w') as f:
                f.write(str(proc.pid))

            time.sleep(0.2)
            return proc
        except Exception as e:
            logger.error(f"Error starting recording with default device: {e}")
            return None

def stop_recording(proc=None):
    """Stops audio recording"""
    if proc:
        # Use the provided process
        recording_process = proc
    else:
        # Try to get the PID from file
        recording_process = None
        try:
            if os.path.exists(PID_FILE):
                with open(PID_FILE, 'r') as f:
                    pid = int(f.read().strip())
                    recording_process = subprocess.Popen(f"ps -p {pid} -o comm=", shell=True, stdout=subprocess.PIPE)
                    output = recording_process.communicate()[0].decode().strip()
                    if "parecord" in output:
                        recording_process = subprocess.Popen(f"kill {pid}", shell=True)
                        recording_process.wait(timeout=1)
                    # Clean up PID file
                    os.remove(PID_FILE)
        except Exception as e:
            logger.error(f"Error stopping recording from PID file: {e}")

    if recording_process:
        try:
            recording_process.terminate()
            try:
                recording_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                recording_process.kill()
                recording_process.wait(timeout=1)
        except Exception as e:
            logger.error(f"Error terminating recording process: {e}")

    # Additional cleanup
    try:
        # killall for any missed processes
        subprocess.run(["killall", "-q", "parecord"], stderr=subprocess.DEVNULL)
    except:
        pass

def is_recording_active():
    pid_file = os.path.expanduser("~/.voice-to-text/recording.pid")
    if not os.path.exists(pid_file):
        return False
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        proc = subprocess.Popen(f"ps -p {pid} -o comm=", shell=True, stdout=subprocess.PIPE)
        output = proc.communicate()[0].decode().strip()
        return "parecord" in output
    except:
        return False

def main():
    # Check if we're already recording
    already_recording = is_recording_active()
    recording_proc = None

    if already_recording:
        # Stop recording mode
        print("Stopping recording and starting transcription...")
        play_sound(SOUND_STOP_RECORDING)
        stop_recording()

        # Short wait to ensure file is properly closed
        time.sleep(0.3)

        # Check if recording file exists and has content
        if not os.path.exists(RECORDING_FILE) or os.path.getsize(RECORDING_FILE) == 0:
            print("Error: Recording file is empty or doesn't exist")
            return 1

        print("\nProcessing the audio file...")

        # Process with Faster Whisper (preferred method)
        if torch.cuda.is_available():
            print("Using GPU for transcription with Faster Whisper...")
        else:
            print(f"Using CPU ({WHISPER_CPU_THREADS} threads) for transcription with Faster Whisper...")

        transcription = transcribe_with_faster_whisper(RECORDING_FILE)

        # Fallback to online services if local transcription fails
        if not transcription and DEEPGRAM_TOKEN:
            print("Local transcription failed, trying Deepgram API...")
            transcription = transcribe_with_deepgram(RECORDING_FILE)
        elif not transcription and OPEN_AI_TOKEN:
            print("Local transcription failed, trying OpenAI API...")
            transcription = transcribe_with_openai(RECORDING_FILE)

        # Show final result
        if transcription:
            print("\nFinal Transcription:")
            print("-" * 50)
            print(transcription)
            print("-" * 50)

            # Save to file
            with open(f"{VOICE_TO_TEXT_DIR}/last_transcription.txt", "w") as f:
                f.write(transcription)

            # Copy to clipboard
            if copy_to_clipboard(transcription):
                print("Transcription copied to clipboard")

                # Paste automatically
                if paste_clipboard():
                    print("Transcription automatically pasted")

            # Play end sound
            play_sound(SOUND_END_TRANSCRIPTION)
        else:
            print("Transcription failed: no text was generated")

    else:
        # Start recording mode - make this as fast as possible
        # Start recording first, then play the sound
        home_dir = os.path.expanduser("~")
        voice_to_text_dir = f"{home_dir}/.voice-to-text"
        os.makedirs(voice_to_text_dir, exist_ok=True)

        print("Starting recording...")
        recording_proc = start_recording()

        if recording_proc:
            # Play start sound after recording has begun
            play_sound(SOUND_START_RECORDING)
            print("Recording started. Run this script again to stop and transcribe.")
        else:
            print("Failed to start recording")
            return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
