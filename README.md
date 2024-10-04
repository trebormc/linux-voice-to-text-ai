# Linux voice to text AI (with Whisper or Deepgram)

## Install

```bash
sudo apt install pulseaudio-utils jq curl xdotool -y
```

You can use the `.env.example` file as a template to create your own `.env` file. Simply duplicate the `.env.example` file, rename it to `.env`, and then fill in the corresponding API key, either for OpenAI or Deepgram, depending on which service you want to use. The `.env` file should be in the same directory as the script. The content of the file will be similar to this:

```
OPEN_AI_TOKEN='sk-xxxx'
# or
DEEPGRAM_TOKEN=xxxx
```

**Recommendation:** While this script supports both OpenAI's Whisper and Deepgram, we highly recommend using Deepgram for your transcription needs. Deepgram offers several advantages:
1. Faster processing times: Deepgram typically transcribes audio more quickly than the Whisper API.
2. Cost-effectiveness: Deepgram is generally more cost-effective, especially for frequent transcription tasks.
3. Improved accuracy: Deepgram tends to have fewer hallucinations compared to OpenAI's Whisper. Whisper has been known to occasionally generate words that were not present in the original audio, while Deepgram typically provides more accurate transcriptions.


## Usage

Start the recording:

```bash
./transcribe.sh
```

Stop the recording and transcribe the audio:

```bash
./transcribe.sh
```

The transcribed text will be automatically copied to your clipboard and pasted at your current cursor position.

## Features

- Supports both OpenAI and Deepgram for transcription
- Automatically limits recording duration (default 2 minutes)
- Plays sound notifications for start, stop, and end of transcription (if configured)
- Supports various clipboard tools (xclip, wl-copy)
- Automatically pastes transcribed text (using xdotool)

## Dependencies

- pulseaudio-utils (parecord)
- jq
- curl
- xdotool
- xclip or wl-copy (for clipboard functionality)

Make sure all dependencies are installed before running the script.

## Keyboard Shortcut Recommendation

For a more convenient usage, it is highly recommended to set up a keyboard shortcut to execute the `transcribe.sh` script. This way, you can start and stop the recording with a simple key combination, making the process much more efficient.

To set up a keyboard shortcut:

1. Open your system's keyboard settings.
2. Add a new custom shortcut.
3. Set the command to the full path of your script, e.g., `/path/to/your/transcribe.sh`
4. Assign a key combination that's easy for you to remember and use, e.g., `Ctrl+Alt+R`

With this setup, you can:
- Press the shortcut once to start recording
- Press it again to stop recording and generate the transcription

This method significantly streamlines the transcription process, allowing you to seamlessly integrate voice-to-text functionality into your workflow without interrupting your typing or navigation.