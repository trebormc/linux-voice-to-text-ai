#!/usr/bin/env python3
import os
import sys
import time
import json
import signal
import tempfile
import subprocess
import threading
import requests
import dotenv
import argparse
from pathlib import Path
import queue

# Determinar directorio de script y cargar variables de entorno
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = SCRIPT_DIR / ".env"
dotenv.load_dotenv(ENV_FILE)

# Configuración desde variables de entorno
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

# Constantes y directorios
HOME_DIR = os.path.expanduser("~")
VOICE_TO_TEXT_DIR = f"{HOME_DIR}/.voice-to-text"
RECORDING_FILE = f"{VOICE_TO_TEXT_DIR}/recording"
TEMP_SEGMENTS_DIR = f"{VOICE_TO_TEXT_DIR}/temp_segments"
STREAMING_OUTPUT_FILE = f"{VOICE_TO_TEXT_DIR}/streaming_output.txt"
SEGMENT_DURATION = 2  # duración en segundos para cada segmento (reducido para mayor reactividad)
AUDIO_FORMAT = "flac"
WHISPER_SERVER_URL = "http://127.0.0.1:5000"

# Variables globales
recording_process = None
recording_active = False
full_transcription = ""
segments_processed = 0
server_streaming_session_active = False
transcription_queue = queue.Queue()
stop_event = threading.Event()

# Preparar directorios
os.makedirs(VOICE_TO_TEXT_DIR, exist_ok=True)
os.makedirs(TEMP_SEGMENTS_DIR, exist_ok=True)

def play_sound(sound_path):
    """Reproduce un sonido usando paplay"""
    if os.path.exists(sound_path):
        try:
            subprocess.run(["paplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"Error reproduciendo sonido: {e}")

def copy_to_clipboard(text):
    """Copia texto al portapapeles usando xclip o wl-copy"""
    try:
        # Intentar con xclip primero
        process = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
        process.communicate(input=text.encode())
        if process.returncode == 0:
            return True

        # Si xclip falla, probar con wl-copy
        process = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
        process.communicate(input=text.encode())
        return process.returncode == 0
    except:
        try:
            # Último recurso: probar wl-copy
            process = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
            process.communicate(input=text.encode())
            return process.returncode == 0
        except:
            print("No se pudo copiar al portapapeles. Instale xclip o wl-copy.")
            return False

def paste_clipboard():
    """Simula presionar Ctrl+V usando xdotool"""
    try:
        time.sleep(0.2)  # pequeña pausa para asegurar que el portapapeles esté listo
        subprocess.run(["xdotool", "key", "ctrl+v"], check=True)
        return True
    except:
        print("No se pudo pegar. Asegúrese de tener xdotool instalado.")
        return False

def check_whisper_server():
    """Verifica si el servidor Whisper está funcionando"""
    try:
        response = requests.get(f"{WHISPER_SERVER_URL}/health", timeout=2)
        return response.status_code == 200
    except:
        return False

def start_streaming_session():
    """Inicia una sesión de streaming con el servidor Whisper"""
    global server_streaming_session_active

    try:
        response = requests.post(f"{WHISPER_SERVER_URL}/stream-start", timeout=5)
        if response.status_code == 200:
            server_streaming_session_active = True
            return True
    except Exception as e:
        print(f"Error al iniciar sesión de streaming: {e}")

    return False

def end_streaming_session():
    """Finaliza la sesión de streaming y devuelve la transcripción final"""
    global server_streaming_session_active

    if not server_streaming_session_active:
        return ""

    try:
        response = requests.post(f"{WHISPER_SERVER_URL}/stream-end", timeout=5)
        if response.status_code == 200:
            server_streaming_session_active = False
            return response.json().get("final_text", "")
    except Exception as e:
        print(f"Error al finalizar sesión de streaming: {e}")

    server_streaming_session_active = False
    return ""

def transcribe_segment_with_whisper_streaming(segment_file):
    """Transcribe un segmento usando la API de streaming del servidor Whisper"""
    if not os.path.exists(segment_file) or os.path.getsize(segment_file) == 0:
        return "", ""

    try:
        with open(segment_file, 'rb') as f:
            files = {'file': f}
            data = {'language': TRANSCRIPTION_LANGUAGE}
            response = requests.post(
                f"{WHISPER_SERVER_URL}/stream-transcribe",
                files=files,
                data=data,
                timeout=10
            )

        if response.status_code == 200:
            json_data = response.json()
            return json_data.get("text", ""), json_data.get("accumulated_text", "")
        else:
            print(f"Error en la transcripción streaming: {response.status_code}")
            return "", ""
    except Exception as e:
        print(f"Error al transcribir segmento streaming: {e}")
        return "", ""

def transcribe_with_whisper(audio_file):
    """Transcribe usando el servidor Whisper local"""
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
            print(f"Error en la transcripción: {response.status_code}")
            return ""
    except Exception as e:
        print(f"Error al transcribir con Whisper: {e}")
        return ""

def transcribe_with_deepgram(audio_file):
    """Transcribe usando la API de Deepgram"""
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
            print(f"Error en la transcripción Deepgram: {response.status_code}")
            return ""
    except Exception as e:
        print(f"Error al transcribir con Deepgram: {e}")
        return ""

def transcribe_with_openai(audio_file):
    """Transcribe usando la API de OpenAI"""
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
            print(f"Error en la transcripción OpenAI: {response.status_code}")
            return ""
    except Exception as e:
        print(f"Error al transcribir con OpenAI: {e}")
        return ""

def start_recording():
    """Inicia la grabación de audio"""
    global recording_process, recording_active

    # Archivo para la grabación
    full_recording = f"{TEMP_SEGMENTS_DIR}/full_recording.{AUDIO_FORMAT}"

    # Comando para grabar
    cmd = [
        "parecord",
        "--channels=1",
        "--format=s16le",
        "--rate=16000",
        "--file-format=flac",
        "--device", AUDIO_INPUT,
        full_recording
    ]

    try:
        # Iniciar proceso de grabación
        recording_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        recording_active = True
        return full_recording
    except Exception as e:
        print(f"Error al iniciar grabación: {e}")

        # Intentar con dispositivo predeterminado
        try:
            cmd[6] = "@DEFAULT_SOURCE@"  # Cambiar a dispositivo predeterminado
            recording_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            recording_active = True
            return full_recording
        except Exception as e:
            print(f"Error al iniciar grabación con dispositivo predeterminado: {e}")
            recording_active = False
            return None

def extract_audio_segment(start_time, duration, output_file):
    """Extrae un segmento de audio del archivo principal en tiempo real"""
    try:
        full_recording = f"{TEMP_SEGMENTS_DIR}/full_recording.{AUDIO_FORMAT}"

        # Verificar si el archivo existe y tiene contenido
        if not os.path.exists(full_recording) or os.path.getsize(full_recording) == 0:
            return False

        # Extraer segmento
        segment_cmd = [
            "ffmpeg", "-y",
            "-i", full_recording,
            "-ss", str(start_time),
            "-t", str(duration),
            "-c:a", "flac",
            output_file
        ]

        subprocess.run(segment_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Verificar si se creó el archivo y tiene contenido
        return os.path.exists(output_file) and os.path.getsize(output_file) > 0
    except Exception as e:
        print(f"Error extrayendo segmento de audio: {e}")
        return False

def audio_segmenter_thread():
    """Hilo que segmenta continuamente el audio para su procesamiento"""
    global segments_processed, recording_active

    segment_index = 0
    while recording_active and not stop_event.is_set():
        # Calcular tiempo de inicio para el segmento actual
        start_time = segment_index * SEGMENT_DURATION

        # Generar nombre para el segmento
        segment_file = f"{TEMP_SEGMENTS_DIR}/segment_{segment_index}.{AUDIO_FORMAT}"

        # Extraer segmento
        if extract_audio_segment(start_time, SEGMENT_DURATION, segment_file):
            # Poner el segmento en la cola para procesamiento
            transcription_queue.put((segment_index, segment_file))
            segment_index += 1

        # Esperar un tiempo menor que la duración del segmento para superposición
        time.sleep(SEGMENT_DURATION * 0.5)

def transcription_processor_thread():
    """Hilo que procesa los segmentos de audio y actualiza la transcripción"""
    global full_transcription, recording_active

    current_text = ""

    while recording_active or not transcription_queue.empty():
        if stop_event.is_set():
            break

        try:
            # Intentar obtener un segmento con timeout
            segment_index, segment_file = transcription_queue.get(timeout=1)

            # Transcribir segmento
            segment_text = ""
            accumulated_text = ""

            if ENABLE_LOCAL_WHISPER:
                segment_text, accumulated_text = transcribe_segment_with_whisper_streaming(segment_file)

                # Actualizar transcripción completa si hay texto acumulado
                if accumulated_text:
                    full_transcription = accumulated_text
                    # Mostrar la última parte del texto que es nueva
                    if len(accumulated_text) > len(current_text):
                        new_text = accumulated_text[len(current_text):]
                        sys.stdout.write(new_text)
                        sys.stdout.flush()
                        current_text = accumulated_text

            # Si hay texto nuevo del segmento pero no hay acumulado, mostrarlo directamente
            elif segment_text:
                sys.stdout.write(segment_text + " ")
                sys.stdout.flush()
                full_transcription += segment_text + " "

            # Marcar tarea como completada
            transcription_queue.task_done()

        except queue.Empty:
            # No hay segmentos disponibles, esperar
            time.sleep(0.1)
        except Exception as e:
            print(f"\nError procesando transcripción: {e}")

def display_transcription_thread():
    """Hilo que muestra la transcripción actualizada en tiempo real"""
    global full_transcription, recording_active

    last_length = 0

    while recording_active:
        if stop_event.is_set():
            break

        # Si hay texto nuevo para mostrar
        if len(full_transcription) > last_length:
            # Mostrar solo el texto nuevo
            new_text = full_transcription[last_length:]
            sys.stdout.write(new_text)
            sys.stdout.flush()
            last_length = len(full_transcription)

        time.sleep(0.1)

def stop_recording():
    """Detiene la grabación de audio"""
    global recording_process, recording_active

    if recording_process and recording_active:
        try:
            recording_process.terminate()
            recording_process.wait(timeout=2)
        except:
            try:
                recording_process.kill()
            except:
                pass

    recording_active = False

def handle_exit(signal, frame):
    """Maneja la señal de interrupción"""
    print("\nInterrumpiendo transcripción...")
    stop_event.set()
    stop_recording()
    if ENABLE_LOCAL_WHISPER and server_streaming_session_active:
        end_streaming_session()
    sys.exit(0)

def wait_for_keypress():
    """Espera hasta que el usuario presione una tecla para detener la grabación"""
    print("Grabando... Presione cualquier tecla para detener.")
    try:
        import termios, fcntl, sys, os
        fd = sys.stdin.fileno()

        # Guardar configuración actual
        old_settings = termios.tcgetattr(fd)

        # Configurar para lectura sin bloqueo
        new_settings = termios.tcgetattr(fd)
        new_settings[3] = new_settings[3] & ~termios.ICANON & ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSANOW, new_settings)

        # Configurar modo no bloqueante
        old_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)

        try:
            while True:
                try:
                    c = sys.stdin.read(1)
                    if c:
                        return
                except IOError:
                    pass
                time.sleep(0.1)

                # También verificar tiempo máximo o evento de parada
                if not recording_active or stop_event.is_set():
                    return
        finally:
            # Restaurar configuración
            termios.tcsetattr(fd, termios.TCSAFLUSH, old_settings)
            fcntl.fcntl(fd, fcntl.F_SETFL, old_flags)
    except:
        # Fallback simple
        input()

def real_time_transcription_system():
    """Implementa el sistema de transcripción en tiempo real con múltiples hilos"""
    global full_transcription

    # Iniciar sesión de streaming si corresponde
    if ENABLE_LOCAL_WHISPER:
        if not start_streaming_session():
            print("No se pudo iniciar sesión de streaming con el servidor Whisper")
            return

    # Iniciar hilo de segmentación de audio
    segmenter = threading.Thread(target=audio_segmenter_thread)
    segmenter.daemon = True
    segmenter.start()

    # Iniciar hilo de procesamiento de transcripción
    processor = threading.Thread(target=transcription_processor_thread)
    processor.daemon = True
    processor.start()

    # Limpiar línea e indicar que estamos listos para transcribir
    print("\nTranscribiendo en tiempo real. Hable ahora:")
    print("-" * 50)

    # Esperar a que el usuario detenga la grabación
    wait_for_keypress()

    # Detener sistema de transcripción
    stop_event.set()

    # Asegurar que todos los hilos terminen correctamente
    segmenter.join(timeout=2)
    processor.join(timeout=2)

    print("\n" + "-" * 50)
    print("Transcripción finalizada.")

def main():
    global recording_active, full_transcription

    # Registrar manejador de señal para Ctrl+C
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # Limpiar archivos temporales antiguos
    for f in os.listdir(TEMP_SEGMENTS_DIR):
        try:
            os.remove(os.path.join(TEMP_SEGMENTS_DIR, f))
        except:
            pass

    # Verificar dependencias
    whisper_server_available = False
    if ENABLE_LOCAL_WHISPER:
        whisper_server_available = check_whisper_server()
        if not whisper_server_available:
            print("Error: El servidor Whisper no está disponible. Ejecute primero ensure_whisper_server.")
            return 1

    # Verificar si hay algún servicio de transcripción configurado
    if not ENABLE_LOCAL_WHISPER and not OPEN_AI_TOKEN and not DEEPGRAM_TOKEN:
        print("Error: No se ha configurado ningún servicio de transcripción.")
        print("Configure ENABLE_LOCAL_WHISPER=true o proporcione OPEN_AI_TOKEN o DEEPGRAM_TOKEN en el archivo .env")
        return 1

    # Reproducir sonido de inicio
    play_sound(SOUND_START_RECORDING)

    # Iniciar grabación
    audio_file = start_recording()
    if not audio_file:
        print("Error: No se pudo iniciar la grabación.")
        return 1

    print(f"Transcripción configurada con:")
    print(f"- Local Whisper: {'Activado' if ENABLE_LOCAL_WHISPER else 'Desactivado'}")
    print(f"- OpenAI API: {'Configurado' if OPEN_AI_TOKEN else 'No configurado'}")
    print(f"- Deepgram API: {'Configurado' if DEEPGRAM_TOKEN else 'No configurado'}")
    print(f"- Idioma: {TRANSCRIPTION_LANGUAGE}")

    # Iniciar sistema de transcripción en tiempo real
    real_time_transcription_system()

    # Detener grabación si aún está activa
    if recording_active:
        stop_recording()

    # Reproducir sonido de detención
    play_sound(SOUND_STOP_RECORDING)

    # Si estamos usando streaming, obtener la transcripción final
    if ENABLE_LOCAL_WHISPER and server_streaming_session_active:
        final_streaming_text = end_streaming_session()
        if final_streaming_text:
            full_transcription = final_streaming_text

    # Si no hay transcripción completa, usar el servicio configurado
    if not full_transcription:
        print("Transcribiendo audio completo...")

        if ENABLE_LOCAL_WHISPER and whisper_server_available:
            print("Usando Whisper local para transcripción final...")
            full_transcription = transcribe_with_whisper(audio_file)
        elif DEEPGRAM_TOKEN:
            print("Usando Deepgram API para transcripción...")
            full_transcription = transcribe_with_deepgram(audio_file)
        elif OPEN_AI_TOKEN:
            print("Usando OpenAI API para transcripción...")
            full_transcription = transcribe_with_openai(audio_file)

    # Mostrar resultado final
    print("\nTranscripción final:")
    print("-" * 50)
    print(full_transcription)
    print("-" * 50)

    # Guardar en archivo
    with open(f"{RECORDING_FILE}.txt", "w") as f:
        f.write(full_transcription)

    # Copiar al portapapeles
    if copy_to_clipboard(full_transcription):
        print("Transcripción copiada al portapapeles")

        # Pegar automáticamente
        if paste_clipboard():
            print("Transcripción pegada automáticamente")

    # Reproducir sonido de finalización
    play_sound(SOUND_END_TRANSCRIPTION)

    return 0

if __name__ == "__main__":
    sys.exit(main())
