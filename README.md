# Linux voice typing

## Install

```bash
sudo apt install xdotool jq curl arecord killall -y
```

You will need to set up an openAI or Deepgram key and put it in the `~/.ai-token` file

```txt
DEEPGRAM_TOKEN=xxxx
OPEN_AI_TOKEN='sk-xxxx'
```

you will need to select a device to record from, you can find the device name with:

```bash
arecord -l
```


## Usage

Start the recording:

```bash
./voice-typing.sh
```

Stop the recording writing the text you spoke to your current cursor position:

```bash
./voice-typing.sh
```
