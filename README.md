# ClipperX Video Editor Worker

RunPod Serverless worker: takes a narration audio track + one image per script
timestamp, cuts silences above a threshold out of the narration (Descript/
Premiere-style auto-cut), re-times the images to match the shortened audio,
and renders the final video (upscaled + encoded at the requested resolution).

No GPU needed — pure ffmpeg/CPU work.

## Input

| Field | Type | Default | Description |
|---|---|---|---|
| `audio_base64` | str | required* | Narration audio, base64 (no `data:` prefix) |
| `audio_url` | str | required* | URL the worker downloads the narration from itself — takes priority over `audio_base64` when both are present |
| `audio_format` | str | `"mp3"` | Container/extension of the input audio |
| `images` | str[] | required* | One base64 PNG/JPEG per segment, in order |
| `image_urls` | str[] | required* | URLs the worker downloads each image from itself — takes priority over `images` |
| `segments` | {start:float}[] | required | Original-audio start time (seconds) per image — same length as `images`/`image_urls` |

\* Either the `*_base64`/`images` form or the `*_url`/`image_urls` form is required for audio and for images (independently), not both. The URL form exists because RunPod rejects job payloads over 10MiB, which a real multi-minute narration + dozens/hundreds of images blows past almost immediately — upload media somewhere fetchable (e.g. a presigned R2/S3 URL) and pass the URLs instead.
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
