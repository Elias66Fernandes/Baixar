from flask import Flask, render_template, request, Response, redirect, url_for
import yt_dlp
import re
import zipstream
import requests
from concurrent.futures import ThreadPoolExecutor
import os

app = Flask(__name__)

def sanitize_filename(name):
    return re.sub(r'[^a-zA-Z0-9_\- ]', '', name)

def stream_audio_m4a(url):
    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "quiet": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        title = sanitize_filename(info.get("title", "audio"))
        audio_url = info['url']
    return title, audio_url

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        link = request.form.get("link")
        tipo = request.form.get("tipo")
        if tipo == "video":
            return redirect(url_for("baixar_video", url=link))
        elif tipo == "playlist":
            return redirect(url_for("baixar_playlist", url=link))
        else:
            return "Tipo de download inválido", 400
    return render_template("index.html")

@app.route("/baixar_video")
def baixar_video():
    url = request.args.get("url")
    if not url:
        return "URL inválida", 400

    title, audio_url = stream_audio_m4a(url)

    def generate():
        with requests.get(audio_url, stream=True) as r:
            r.raise_for_status()
            for chunk in r.iter_content(chunk_size=131072):  # 128 KB
                yield chunk

    return Response(
        generate(),
        mimetype="audio/m4a",
        headers={"Content-Disposition": f"attachment; filename={title}.m4a"}
    )

@app.route("/baixar_playlist")
def baixar_playlist():
    url = request.args.get("url")
    if not url:
        return "URL inválida", 400

    z = zipstream.ZipFile(mode='w', compression=zipstream.ZIP_DEFLATED)

    ydl_opts = {"quiet": True, "extract_flat": "in_playlist"}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        entries = info.get("entries", [info])

    def fetch_audio(entry):
        video_url = entry.get("url")
        title, audio_url = stream_audio_m4a(video_url)
        r = requests.get(audio_url, stream=True)
        return f"{title}.m4a", r.iter_content(chunk_size=131072)  # 128 KB

    # Threads limitadas para não travar o Render Free
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = executor.map(fetch_audio, entries)

        for filename, stream_iter in results:
            z.write_iter(filename, stream_iter)

    return Response(
        z,
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=playlist.zip"}
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)



