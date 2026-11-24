#!/bin/sh
# Hermes command STT provider: ENGINE_DIR INPUT OUTPUT LANGUAGE
set -eu
umask 077
engine=$1
audio=$2
output=$3
language=$4
work=$(mktemp -d "$(dirname "$output")/ryze-stt.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
ffmpeg -nostdin -v error -i "$audio" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$work/input.wav"
"$engine/whisper-cli" -m "$engine/model.bin" -f "$work/input.wav" -l "$language" -t 2 -ng -nt -otxt -of "$work/transcript" >/dev/null
test -s "$work/transcript.txt"
cp -- "$work/transcript.txt" "$output"
