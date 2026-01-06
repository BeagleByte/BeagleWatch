import logging
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

def count_markdown_files():
    return sum(1 for p in CONTENT_DIR.glob("**/*") if p.is_file() and p.suffix.lower() in ALLOWED_EXT)

def list_markdown_files(offset=0, limit=None):
    files = []
    files_in_content = [p for p in CONTENT_DIR.glob("**/*") if p.is_file()]
    files_sorted = sorted(files_in_content, key=lambda p: p.stat().st_mtime, reverse=True)
    if limit is not None:
        files_sorted = files_sorted[offset: offset + limit]
    # rest unchanged: build files list from files_sorted ...
    for p in files_sorted:
        if p.suffix.lower() in ALLOWED_EXT:
            try:
                post = frontmatter.load(p)
            except Exception:
                post = None
            metadata = post.metadata if post else {}
            title = metadata.get("title") if post else p.stem
            if not title:
                title = p.stem
            image = metadata.get("image")
            if not image and post:
                import re
                m = re.search(r'![[^]]*](([^)]+))', post.content)
                if m:
                    image = m.group(1)
            image_url = None
            if image:
                img_path = (p.parent / image).resolve() if not os.path.isabs(image) else pathlib.Path(image)
                try:
                    if CONTENT_DIR in img_path.parents or img_path == CONTENT_DIR:
                        rel = img_path.relative_to(CONTENT_DIR)
                        image_url = url_for("content_file", path=str(rel))
                except Exception:
                    image_url = None
            files.append({
                "filename": str(p.relative_to(CONTENT_DIR)),
                "title": title,
                "metadata": metadata,
                "image_url": image_url,
            })
    return files

@app.route("/")
def index():
    page = request.args.get("page", 1, type=int)
    PER_PAGE = 20
    total = count_markdown_files()
    last_page = (total + PER_PAGE - 1) // PER_PAGE
    if page < 1 or page > max(1, last_page):
        abort(404)
    offset = (page - 1) * PER_PAGE
    files = list_markdown_files(offset=offset, limit=PER_PAGE)
    return render_template("index.html", files=files, page=page, last_page=last_page)

@app.route("/api/files")
def api_files():
    page = request.args.get("page", 1, type=int)
    PER_PAGE = 20
    total = count_markdown_files()
    last_page = (total + PER_PAGE - 1) // PER_PAGE
    if page < 1 or page > max(1, last_page):
        return jsonify({"ok": False, "error": "page out of range"}), 400
    offset = (page - 1) * PER_PAGE
    files = list_markdown_files(offset=offset, limit=PER_PAGE)
    return jsonify({"ok": True, "page": page, "last_page": last_page, "total": total, "files": files})

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
