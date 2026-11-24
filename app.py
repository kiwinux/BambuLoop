"""Optional local HTTP API for BambuLoop. The site also runs on a static host."""

from functools import partial
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from i18n_helper import t_dict
from job_service import INPUT_LIMIT, OPERATIONS, JobError, JobFiles, dispatch


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(BASE_DIR / "docs"), static_url_path="")
app.config.update(MAX_CONTENT_LENGTH=INPUT_LIMIT, UPLOAD_FOLDER=str(UPLOAD_DIR), OUTPUT_FOLDER=str(OUTPUT_DIR))


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.post("/api/upload")
def api_upload():
    incoming = request.files.getlist("gcode_files")
    if not incoming:
        return jsonify(error=t_dict("error.no_file")), 400
    store = JobFiles(UPLOAD_DIR, OUTPUT_DIR)
    files, errors = [], []
    for upload in incoming:
        if not upload.filename:
            continue
        staged = None
        try:
            stored = store.stage(upload.filename)
            staged = store.uploads / stored
            upload.save(staged)
            result = store.import_staged(upload.filename, stored)
            files.extend(result["files"])
            errors.extend(result["errors"])
        except JobError as error:
            errors.append(dict(filename=upload.filename, message=error.payload["error"]))
        except OSError as error:
            if staged:
                staged.unlink(missing_ok=True)
            errors.append(dict(filename=upload.filename, message=str(error)))
    return jsonify(files=files, errors=errors)


def _operation(action):
    status, body = dispatch(JobFiles(UPLOAD_DIR, OUTPUT_DIR), action, request.get_json(silent=True) or {})
    return jsonify(body), status


for operation in OPERATIONS:
    app.add_url_rule("/api/" + operation, "api_" + operation, partial(_operation, operation),
                     methods=["GET" if operation == "sound_presets" else "POST"])


@app.get("/api/download/<path:filename>")
def api_download(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


@app.post("/api/reset")
def api_reset():
    for directory in (UPLOAD_DIR, OUTPUT_DIR):
        for entry in directory.iterdir():
            if entry.is_file():
                entry.unlink()
    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
