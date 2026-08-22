

import os
import traceback

from flask import Flask, request, jsonify, render_template

from utils.extract import extract_text, is_supported_file, ExtractionError
from utils.summarize import summarize, SummarizationError, ensure_nltk_data

MAX_CONTENT_LENGTH = 15 * 1024 * 1024  # 15 MB

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

ensure_nltk_data()


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"error": "File is too large. Maximum size is 15 MB."}), 413


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/process")
def process_document():
    if "file" not in request.files:
        return jsonify({"error": "No file was uploaded."}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"error": "No file was selected."}), 400

    if not is_supported_file(file.filename):
        return jsonify(
            {"error": "Unsupported file type. Please upload a PDF or an image "
                      "(PNG, JPG, BMP, TIFF)."}
        ), 400

    length = request.form.get("length", "medium")
    if length not in ("short", "medium", "long"):
        length = "medium"

    file_bytes = file.read()

    try:
        extraction = extract_text(file.filename, file_bytes)
    except ExtractionError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected error while extracting text from the file: {exc}"}), 500

    try:
        result = summarize(extraction["text"], length=length)
    except SummarizationError as exc:
        return jsonify({"error": str(exc)}), 422
    except LookupError:
    
        try:
            ensure_nltk_data(force=True)
            result = summarize(extraction["text"], length=length)
        except Exception:
            traceback.print_exc()
            return jsonify({
                "error": "The summarizer's language data isn't installed and "
                         "couldn't be downloaded automatically. Run: python -c "
                         "\"import nltk; nltk.download('punkt'); nltk.download('punkt_tab')\" "
                         "and try again."
            }), 500
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": f"Unexpected error while generating the summary: {exc}"}), 500

    return jsonify({
        "filename": file.filename,
        "extraction_method": extraction["method"],
        "length": length,
        "summary": result["summary"],
        "key_points": result["key_points"],
        "suggestions": result["suggestions"],
        "stats": result["stats"],
        "extracted_text": extraction["text"],
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
