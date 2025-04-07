#!/usr/bin/env python3
import sys
import os
import requests
import time
import subprocess
import signal

def is_server_running():
    # Verificar si el archivo PID existe
    pid_file = os.path.expanduser("~/.whisper_server.pid")
    if not os.path.exists(pid_file):
        return False

    # Leer el PID y verificar si ese proceso está corriendo
    try:
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())

        # Verificar si el proceso existe
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read().decode('utf-8', errors='ignore')
            if "whisper_server.py" in cmdline:
                return True
    except (ValueError, FileNotFoundError, IOError):
        pass

    # Limpiar archivo PID obsoleto
    try:
        os.remove(pid_file)
    except:
        pass

    return False

def start_server():
    print("Starting Whisper server...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    server_path = os.path.join(script_dir, "whisper_server.py")

    # Asegurar que el archivo tiene permisos de ejecución
    os.chmod(server_path, 0o755)

    # Instalar dependencias necesarias
    try:
        import flask
    except ImportError:
        print("Installing Flask...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])

    # Iniciar el servidor en segundo plano
    server_process = subprocess.Popen(
        [sys.executable, server_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True
    )

    # Esperar hasta que el servidor esté listo (con timeout)
    start_time = time.time()
    while time.time() - start_time < 120:  # 2 minutos de timeout
        try:
            # Verificar si el servidor responde
            if os.path.exists(os.path.expanduser("~/.whisper_server.pid")):
                time.sleep(5)  # Dar tiempo para que el modelo se cargue completamente
                return True
        except:
            pass
        time.sleep(1)

    print("Error: Timeout waiting for server to start")
    return False

def transcribe_audio(audio_file, language="es"):
    # Asegurarse de que el servidor esté corriendo
    if not is_server_running():
        if not start_server():
            print("Failed to start the transcription server")
            return None

    print(f"Sending audio to transcription service...")
    try:
        with open(audio_file, 'rb') as f:
            files = {'file': f}
            data = {'language': language}
            response = requests.post('http://127.0.0.1:5000/transcribe',
                                    files=files,
                                    data=data,
                                    timeout=180)  # 3 minutos de timeout

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

    # Instalar requests si no está disponible
    try:
        import requests
    except ImportError:
        print("Installing required dependency: requests")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        import requests

    # Transcribir
    result = transcribe_audio(audio_file, language)
    if result:
        print(f"Transcription complete")
    else:
        print("Transcription failed")
