import runpod
import base64
import subprocess
import re
import os
import tempfile
import urllib.request


def decode_to_file(b64_data, path):
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64_data))


def download_to_file(url, path):
    urllib.request.urlretrieve(url, path)


def upload_via_put(url, path):
    with open(path, "rb") as f:
        data = f.read()
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", "video/mp4")
    with urllib.request.urlopen(req) as resp:
        if resp.status not in (200, 201):
            raise RuntimeError(f"output upload failed: HTTP {resp.status}")


def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def get_duration(path):
    cmd = (
        f'ffprobe -v error -show_entries format=duration '
        f'-of default=noprint_wrappers=1:nokey=1 "{path}"'
    )
    result = run(cmd)
    return float(result.stdout.strip())


def detect_silences(audio_path, threshold_db=-40, min_duration=0.4):
    cmd = (
        f'ffmpeg -i "{audio_path}" '
        f'-af "silencedetect=noise={threshold_db}dB:d={min_duration}" -f null - 2>&1'
    )
    result = run(cmd)
    output = result.stdout + result.stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", output)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", output)]
    n = min(len(starts), len(ends))
    return list(zip(starts[:n], ends[:n]))


def build_keep_segments(total_duration, silences):
    """Inverse of the silences: the audio spans we actually keep."""
    keep = []
    cursor = 0.0
    for s, e in silences:
        if s > cursor:
            keep.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < total_duration:
        keep.append((cursor, total_duration))
    return keep


def remap_time(t, silences):
    """Map an original-audio timestamp to its new timestamp after the
    detected silences are cut out. A timestamp that falls inside a removed
    gap collapses to that gap's (post-cut) start position."""
    removed = 0.0
    for s, e in silences:
        if e <= t:
            removed += e - s
        elif s <= t < e:
            return s - removed
        else:
            break
    return t - removed


def trim_silences(audio_path, keep_segments, out_path, workdir):
    if not keep_segments:
        return audio_path

    # Extract each "keep" span to its own file, then join with the concat
    # demuxer (a plain file list — no filtergraph, so no risk of hitting the
    # shell's max command-length with hundreds of segments).
    segment_dir = os.path.join(workdir, "audio_segments")
    os.makedirs(segment_dir, exist_ok=True)
    concat_list_path = os.path.join(workdir, "audio_concat.txt")
    lines = []
    for i, (s, e) in enumerate(keep_segments):
        seg_path = os.path.join(segment_dir, f"seg_{i:04d}.aac")
        cmd = (
            f'ffmpeg -i "{audio_path}" -ss {s} -to {e} '
            f'-c:a aac -b:a 192k "{seg_path}" -y'
        )
        result = run(cmd)
        if not os.path.exists(seg_path) or os.path.getsize(seg_path) == 0:
            raise RuntimeError(f"segment {i} extraction failed: {result.stderr[-2000:]}")
        lines.append(f"file '{seg_path}'")
    with open(concat_list_path, "w") as f:
        f.write("\n".join(lines))

    cmd = f'ffmpeg -f concat -safe 0 -i "{concat_list_path}" -c copy "{out_path}" -y'
    result = run(cmd)
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"trim_silences concat failed: {result.stderr[-3000:]}")
    return out_path


def handler(event):
    inp = event["input"]
    workdir = tempfile.mkdtemp()

    audio_format = inp.get("audio_format", "mp3")
    audio_path = os.path.join(workdir, f"audio_in.{audio_format}")
    # `audio_url` (o worker baixa ele mesmo) tem prioridade sobre
    # `audio_base64` — usado pela produção automática de vídeo pra evitar
    # embutir a narração inteira (vários MB) no corpo do job, que tem
    # limite de 10MiB no RunPod. Uploads feitos via URL pré-assinada do R2.
    if "audio_url" in inp:
        download_to_file(inp["audio_url"], audio_path)
    else:
        decode_to_file(inp["audio_base64"], audio_path)

    threshold_db = inp.get("silence_threshold_db", -40)
    min_silence = inp.get("min_silence_duration", 0.4)
    cut_silences = inp.get("cut_silences", True)

    total_duration = get_duration(audio_path)

    if cut_silences:
        silences = detect_silences(audio_path, threshold_db, min_silence)
        keep_segments = build_keep_segments(total_duration, silences)
        trimmed_audio_path = trim_silences(
            audio_path, keep_segments, os.path.join(workdir, "audio_trimmed.aac"), workdir
        )
    else:
        silences = []
        trimmed_audio_path = audio_path

    new_total_duration = get_duration(trimmed_audio_path)

    # Mesma prioridade: `image_urls` (baixadas pelo worker) sobre `images`
    # (base64 embutido) — mesmo motivo do áudio, só que ainda mais crítico
    # aqui porque um vídeo real tem dezenas/centenas de imagens.
    if "image_urls" in inp:
        image_sources = inp["image_urls"]
        sources_are_urls = True
    else:
        image_sources = inp["images"]
        sources_are_urls = False
    segments = inp["segments"]  # list of {"start": float} in original-audio seconds
    if len(image_sources) != len(segments):
        return {"error": f"images ({len(image_sources)}) and segments ({len(segments)}) length mismatch"}

    image_paths = []
    for i, src in enumerate(image_sources):
        p = os.path.join(workdir, f"img_{i:04d}.png")
        if sources_are_urls:
            download_to_file(src, p)
        else:
            decode_to_file(src, p)
        image_paths.append(p)

    new_starts = [remap_time(seg["start"], silences) for seg in segments]

    concat_list_path = os.path.join(workdir, "concat.txt")
    lines = []
    for i in range(len(image_paths)):
        if i < len(image_paths) - 1:
            dur = new_starts[i + 1] - new_starts[i]
        else:
            dur = new_total_duration - new_starts[i]
        dur = max(dur, 0.05)
        lines.append(f"file '{image_paths[i]}'")
        lines.append(f"duration {dur:.3f}")
    lines.append(f"file '{image_paths[-1]}'")
    with open(concat_list_path, "w") as f:
        f.write("\n".join(lines))

    width = inp.get("width", 1920)
    height = inp.get("height", 1080)
    crf = inp.get("crf", 16)
    fps = inp.get("fps", 24)

    output_path = os.path.join(workdir, "output.mp4")
    cmd = (
        f'ffmpeg -f concat -safe 0 -i "{concat_list_path}" -i "{trimmed_audio_path}" '
        f'-vf "scale={width}:{height}:flags=lanczos,format=yuv420p" '
        f'-fps_mode cfr -c:v libx264 -preset medium -crf {crf} -r {fps} '
        f'-c:a aac -b:a 192k -shortest "{output_path}" -y'
    )
    result = run(cmd)

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        return {"error": "ffmpeg failed to produce output", "stderr": result.stderr[-4000:]}

    stats = {
        "original_duration": total_duration,
        "new_duration": new_total_duration,
        "time_saved": round(total_duration - new_total_duration, 3),
        "silences_cut": len(silences),
    }

    # `output_upload_url` (PUT pré-assinada do R2) tem prioridade sobre
    # devolver o vídeo em base64 no corpo da resposta — testado na prática,
    # um vídeo real (MP4 + ~33% do base64) estoura o limite de payload de
    # RESULTADO do RunPod, e o job volta "COMPLETED" mas sem o campo
    # `output` nenhum (descartado silenciosamente). Mesmo motivo que já nos
    # fez usar URL em vez de base64 do lado da entrada (áudio/imagens).
    if "output_upload_url" in inp:
        upload_via_put(inp["output_upload_url"], output_path)
        return stats

    with open(output_path, "rb") as f:
        video_b64 = base64.b64encode(f.read()).decode("utf-8")
    return {"video_base64": video_b64, **stats}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
