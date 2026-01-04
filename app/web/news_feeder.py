import os
import pathlib
import threading
import frontmatter
import markdown
from bs4 import BeautifulSoup
from flask import Flask, render_template, send_from_directory, request, url_for, jsonify, abort

BASE_DIR = pathlib.Path(__file__).parent.resolve()
print(BASE_DIR)

#relative path to content
CONTENT_DIR = (BASE_DIR / "../content").resolve()

app = Flask(__name__)
app.secret_key = "change-me-to-a-secure-key"  # replace in production

ALLOWED_EXT = {".md", ".markdown"}

def list_markdown_files():
    files = []
    files_in_content = [p for p in CONTENT_DIR.glob("**/*") if p.is_file()]
    files_sorted = sorted(files_in_content, key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files_sorted:
        if p.is_file() and p.suffix.lower() in ALLOWED_EXT:
            try:
                post = frontmatter.load(p)
            except Exception as e:
                post = None
            title = None
            metadata = {}
            if post:
                metadata = post.metadata or {}
                # reasonable default title: YAML title or filename (without ext)
                title = metadata.get("title") or p.stem
            else:
                title = p.stem
            # find first image referenced in markdown or metadata.image
            image = metadata.get("image")
            if not image and post:
                # simple heuristic: scan content for ![alt](path)
                import re
                m = re.search(r'!\[[^]]*]\(([^)]+)\)', post.content)
                if m:
                    image = m.group(1)
            # sanitize image path: if relative and exists in content dir, build URL
            image_url = None
            if image:
                img_path = (p.parent / image).resolve() if not os.path.isabs(image) else pathlib.Path(image)
                try:
                    # ensure the image is inside content dir
                    if CONTENT_DIR in img_path.parents or img_path == CONTENT_DIR:
                        # create a URL that serves static content from /content-files/<relative path>
                        rel = img_path.relative_to(CONTENT_DIR)
                        image_url = url_for("content_file", path=str(rel))
                except Exception as e:
                    print(e)
            else:
                image_url = None
            files.append({
                "filename": str(p.relative_to(CONTENT_DIR)),  # relative path used as id
                "title": title,
                "metadata": metadata,
                "image_url": image_url,
            })

    return files

@app.route("/")
def index():
    files = list_markdown_files()
    return render_template("index.html", files=files)

@app.route("/content/<path:path>")
def content_file(path):
    safe_path = (CONTENT_DIR / path).resolve()
    # ensure the served file is within CONTENT_DIR
    if CONTENT_DIR not in safe_path.parents and safe_path != CONTENT_DIR:
        abort(404)
    return send_from_directory(str(CONTENT_DIR), path)

@app.route("/view/<path:md_path>")
def view_markdown(md_path):
    file_path = (CONTENT_DIR / md_path).resolve()
    print(file_path)
    if not file_path.exists() or CONTENT_DIR not in file_path.parents and file_path != CONTENT_DIR:
        abort(404)
    post = frontmatter.load(file_path)
    html = markdown.markdown(post.content, extensions=["fenced_code", "tables", "toc"])

    soup = BeautifulSoup(html, 'html.parser')
    clean = soup.get_text()
    return render_template("view_md.html", html=clean, metadata=post.metadata, title=post.metadata.get("title", file_path.stem))

# Example background action: run a function in a thread
def background_action(file_rel_path):
    # Replace this with your real task (e.g., indexing, analysis, conversion).
    # This demo just writes a simple log file next to the markdown.
    try:
        target = (CONTENT_DIR / file_rel_path).resolve()
        with open(target.with_suffix(target.suffix + ".action.log"), "a", encoding="utf8") as f:
            f.write(f"Action executed on {file_rel_path}\n")
    except Exception as e:
        app.logger.exception("Background action failed: %s", e)

@app.route("/action", methods=["POST"])
def action():
    data = request.get_json() or request.form
    file_rel = data.get("file")
    if not file_rel:
        return jsonify({"ok": False, "error": "missing file parameter"}), 400
    # validate path
    target = (CONTENT_DIR / file_rel).resolve()
    if not target.exists() or (CONTENT_DIR not in target.parents and target != CONTENT_DIR):
        return jsonify({"ok": False, "error": "file not found"}), 404
    # run background job
    t = threading.Thread(target=background_action, args=(file_rel,), daemon=True)
    t.start()
    return jsonify({"ok": True, "message": "action started", "file": file_rel})

if __name__ == "__main__":
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)
    app.run(debug=True, host="127.0.0.1", port=5000)
