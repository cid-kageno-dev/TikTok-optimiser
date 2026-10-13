import os, json, shutil, subprocess, tempfile, zipfile
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file, after_this_request
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "2048")) * 1024 * 1024
ROOT = Path(tempfile.gettempdir()) / "tikutils_web_jobs"
ROOT.mkdir(parents=True, exist_ok=True)
ALLOWED = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}

def tool_exists(name):
    return shutil.which(name) is not None

def probe(path):
    if not tool_exists("ffprobe"):
        raise RuntimeError("ffprobe is missing. Install FFmpeg on the server.")
    p = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=120)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or "Could not read this video.")
    data = json.loads(p.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or 0)
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
    try:
        a,b = rate.split("/")
        fps = float(a)/float(b) if float(b) else 0
    except Exception:
        fps = 0
    size = int(fmt.get("size") or Path(path).stat().st_size)
    bitrate = int(float(fmt.get("bit_rate") or (size*8/duration if duration else 0)))
    return {
        "filename": Path(path).name, "size": size, "size_mb": round(size/1048576, 2),
        "duration": round(duration, 3), "duration_label": f"{int(duration//60):02d}:{duration%60:05.2f}",
        "width": int(video.get("width") or 0), "height": int(video.get("height") or 0),
        "fps": round(fps, 3), "fps_label": f"{fps:.3f}".rstrip("0").rstrip("."),
        "video_codec": video.get("codec_name", "Unknown"), "audio_codec": audio.get("codec_name", "None"),
        "bitrate": bitrate, "bitrate_mbps": round(bitrate/1_000_000, 2),
        "is_4k": max(int(video.get("width") or 0), int(video.get("height") or 0)) >= 3840,
        "is_60fps": fps >= 59.0,
        "format": fmt.get("format_name", "Unknown")
    }

@app.get("/")
def home():
    return render_template("index.html")

@app.get("/api/status")
def status():
    return jsonify({"ffmpeg": tool_exists("ffmpeg"), "ffprobe": tool_exists("ffprobe")})

@app.post("/api/analyze")
def analyze():
    files = request.files.getlist("videos")
    if not files or all(not f.filename for f in files):
        return jsonify(error="Choose at least one video file."), 400
    results, errors = [], []
    job = ROOT / next(tempfile._get_candidate_names())
    job.mkdir()
    for f in files:
        name = secure_filename(f.filename or "")
        if not name or Path(name).suffix.lower() not in ALLOWED:
            errors.append({"filename": f.filename or "unknown", "error": "Unsupported file type."})
            continue
        path = job / name
        f.save(path)
        try:
            results.append(probe(path))
        except Exception as e:
            errors.append({"filename": name, "error": str(e)})
    shutil.rmtree(job, ignore_errors=True)
    return jsonify(results=results, errors=errors)

@app.post("/api/optimize")
def optimize():
    if not tool_exists("ffmpeg") or not tool_exists("ffprobe"):
        return jsonify(error="FFmpeg and ffprobe must be installed on the server."), 503
    files = request.files.getlist("videos")
    if not files or all(not f.filename for f in files):
        return jsonify(error="Choose at least one video file."), 400
    preset = request.form.get("preset", "balanced")
    crf = {"high": "18", "balanced": "21", "small": "24"}.get(preset, "21")
    job = ROOT / next(tempfile._get_candidate_names())
    job.mkdir()
    outputs, errors = [], []
    for f in files:
        name = secure_filename(f.filename or "")
        if not name or Path(name).suffix.lower() not in ALLOWED:
            errors.append(f"{f.filename or 'unknown'}: unsupported file type")
            continue
        src = job / ("input_" + name)
        out = job / (Path(name).stem + "_optimized.mp4")
        f.save(src)
        try:
            before = probe(src)
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                   "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium",
                   "-crf", crf, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                   "-movflags", "+faststart", "-map_metadata", "0", str(out)]
            # Avoid upscaling; retain source dimensions and frame rate.
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if p.returncode or not out.exists():
                raise RuntimeError((p.stderr or "FFmpeg encoding failed")[-1200:])
            after = probe(out)
            outputs.append({"filename": out.name, "before_mb": before["size_mb"],
                            "after_mb": after["size_mb"],
                            "saved_percent": round((1-after["size"]/before["size"])*100, 1) if before["size"] else 0,
                            "path": str(out)})
        except Exception as e:
            errors.append(f"{name}: {e}")
        finally:
            try: src.unlink(missing_ok=True)
            except Exception: pass
    if not outputs:
        shutil.rmtree(job, ignore_errors=True)
        return jsonify(error="No files could be optimized.", details=errors), 422
    if len(outputs) == 1:
        path = Path(outputs[0]["path"])
        @after_this_request
        def cleanup(response):
            shutil.rmtree(job, ignore_errors=True)
            return response
        return send_file(path, as_attachment=True, download_name=path.name, mimetype="video/mp4")
    archive = job / "tikutils_optimized.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for item in outputs:
            z.write(item["path"], arcname=item["filename"])
    @after_this_request
    def cleanup(response):
        shutil.rmtree(job, ignore_errors=True)
        return response
    return send_file(archive, as_attachment=True, download_name="tikutils_optimized.zip")

@app.errorhandler(413)
def too_large(_):
    return jsonify(error="Upload limit exceeded. Increase MAX_UPLOAD_MB on your server."), 413

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
