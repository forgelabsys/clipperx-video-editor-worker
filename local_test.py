import sys
import json
import base64
import glob
import os

sys.path.insert(0, os.path.dirname(__file__))
from handler import handler  # noqa: E402

SCRATCH = "C:/Users/User/AppData/Local/Temp/claude/C--devs-clipperX/637cad22-792b-4a06-a23a-a76cf9bc406c/scratchpad"
IMG_DIR = "C:/devs/clipperx-studio/galloping-gertie/imagens"

with open(os.path.join(SCRATCH, "narracao_segments.json")) as f:
    segments = json.load(f)

with open(os.path.join(SCRATCH, "narracao_completa.mp3"), "rb") as f:
    audio_b64 = base64.b64encode(f.read()).decode()

files = sorted(glob.glob(os.path.join(IMG_DIR, "*.png")))
assert len(files) == 175, f"expected 175 images, found {len(files)}"

images_b64 = []
for fp in files:
    with open(fp, "rb") as f:
        images_b64.append(base64.b64encode(f.read()).decode())

event = {
    "input": {
        "audio_base64": audio_b64,
        "audio_format": "mp3",
        "images": images_b64,
        "segments": [{"start": s["start"]} for s in segments],
        "cut_silences": True,
        "silence_threshold_db": -40,
        "silence_min_duration": 0.4,
        "width": 1920,
        "height": 1080,
        "crf": 18,
        "fps": 24,
    }
}

result = handler(event)
video_b64 = result.pop("video_base64", None)
print(json.dumps(result, indent=2))
if video_b64:
    out_path = os.path.join(SCRATCH, "worker_local_test_output.mp4")
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(video_b64))
    print("saved:", out_path)
else:
    print("NO VIDEO PRODUCED")
