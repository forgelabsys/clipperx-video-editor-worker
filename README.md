# ClipperX Video Editor Worker

RunPod Serverless worker: takes a narration audio track + one image per script
timestamp, cuts silences above a threshold out of the narration (Descript/
Premiere-style auto-cut), re-times the images to match the shortened audio,
and renders the final video (upscaled + encoded at the requested resolution).

No GPU needed — pure ffmpeg/CPU work.

## Input

| Field | Type | Default | Description |
|---|---|---|---|
| `audio_base64` | str | required | Narration audio, base64 (no `data:` prefix) |
| `audio_format` | str | `"mp3"` | Container/extension of the input audio |
| `images` | str[] | required | One base64 PNG/JPEG per segment, in order |
| `segments` | {start:float}[] | required | Original-audio start time (seconds) per image — same length as `images` |
| `cut_silences` | bool | `true` | Whether to auto-cut silences |
| `silence_threshold_db` | number | `-40` | Volume (dBFS) below which audio is considered silence |
| `silence_min_duration` | number | `0.4` | Minimum gap length (seconds) to be cut |
| `width` / `height` | int | `1920` / `1080` | Output video resolution |
| `crf` | int | `16` | x264 quality (lower = better/bigger) |
| `fps` | int | `24` | Output frame rate |

## Output

```json
{
  "video_base64": "...",
  "original_duration": 470.86,
  "new_duration": 402.11,
  "time_saved": 68.75,
  "silences_cut": 132
}
```

## Local test

```bash
docker build -t clipperx-video-editor .
docker run --rm -v "$PWD/test_input.json:/app/test_input.json" clipperx-video-editor \
  python3 handler.py --test_input /app/test_input.json
```
