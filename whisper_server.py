#!/usr/bin/env python3
import torch
from transformers import pipeline
from flask import Flask, request, jsonify
import os
import signal

app = Flask(__name__)

# Carga el modelo solo una vez al iniciar
print("Loading Whisper model...")
device = "cuda:0" if torch.cuda.is_available() else "cpu"
# Usar un modelo más pequeño para mejor rendimiento en CPU
model_id = "openai/whisper-small"  # Más rápido que large-v3

pipe = pipeline(
    "automatic-speech-recognition",
    model=model_id,
    torch_dtype=torch.float32,
    device=device,
)
print(f"Model loaded on {device}")

# Guardar el PID para poder verificar que el servidor está en ejecución
with open(os.path.expanduser("~/.whisper_server.pid"), "w") as f:
    f.write(str(os.getpid()))

@app.route('/transcribe', methods=['POST'])
def transcribe():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    language = request.form.get('language', 'es')

    # Guardar temporalmente
    temp_path = f"/tmp/whisper_temp_{os.getpid()}.flac"
    file.save(temp_path)

    try:
        # CORRECCIÓN: Usar generate_kwargs para el idioma
        result = pipe(
            temp_path,
            chunk_length_s=30,
            batch_size=8,
            return_timestamps=False,
            generate_kwargs={"language": language}  # Pasar idioma correctamente
        )

        return jsonify({"text": result["text"]})
    finally:
        # Limpiar archivo temporal
        if os.path.exists(temp_path):
            os.remove(temp_path)

# Para garantizar una salida limpia
def signal_handler(sig, frame):
    print('Shutting down whisper server...')
    if os.path.exists(os.path.expanduser("~/.whisper_server.pid")):
        os.remove(os.path.expanduser("~/.whisper_server.pid"))
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == '__main__':
    # Instalar Flask si no está disponible
    try:
        app.run(host='127.0.0.1', port=5000)
    except ModuleNotFoundError:
        import subprocess
        import sys
        print("Installing Flask...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
        app.run(host='127.0.0.1', port=5000)
