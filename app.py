from flask import Flask, render_template, request, Response, redirect, url_for
import yt_dlp
import re
import zipstream
from concurrent.futures import ThreadPoolExecutor
import os
import shutil # NOVO: Adicionado para ajudar na limpeza de diretórios

app = Flask(__name__)

COOKIES_FILE = "cookies.txt"
TEMP_DIR = "temp_downloads" # Diretório para arquivos MP3 temporários

def sanitize_filename(name):
    return re.sub(r'[^a-zA-Z0-9_\- ]', '', name)

# NOVO: Esta função faz o download e converte o áudio para MP3 localmente usando FFmpeg
# IMPORTANTE: Requer que o FFmpeg esteja instalado no ambiente do servidor.
def download_audio_mp3_locally(url):
    # Garante que o diretório temporário exista
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    # Define o template de saída para o yt-dlp
    output_template = os.path.join(TEMP_DIR, '%(title)s.%(ext)s')
    
    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{ # Configuração para conversão para MP3
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192", # Qualidade de áudio: 192kbps
        }],
        "outtmpl": output_template,
        "quiet": True,
        "noplaylist": True,
        "cookiefile": COOKIES_FILE,
        "ignoreerrors": True, 
    }
    
    final_filepath = None
    title = None
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Baixa e converte
            info = ydl.extract_info(url, download=True)
            
            if info:
                # Obtém as informações do vídeo (pode ser uma lista se a URL era uma playlist, mas apenas o primeiro é processado aqui)
                video_info = info['entries'][0] if 'entries' in info and info['entries'] else info

                if video_info:
                    title = sanitize_filename(video_info.get("title", "audio"))
                    
                    # yt-dlp renomeia o arquivo, precisamos do nome final (com a extensão 'mp3')
                    base_name = ydl.prepare_filename(video_info)
                    final_filepath = base_name.replace(video_info['ext'], 'mp3')
                    
                    # Verificação de segurança (caso o yt-dlp falhe em retornar o caminho correto)
                    if not os.path.exists(final_filepath):
                        print(f"ATENÇÃO: Arquivo MP3 não encontrado após download para {url}")
                        return None, None
                        
                    return f"{title}.mp3", final_filepath
            
    except yt_dlp.utils.DownloadError as e:
        print(f"ERRO de Download/yt-dlp para {url}: {e}")
    except Exception as e:
        print(f"ERRO Inesperado ao processar {url}: {e}")
        
    return None, None

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

    # Faz o download local e a conversão para MP3
    title_with_ext, final_filepath = download_audio_mp3_locally(url)
    
    if not final_filepath:
        return f"Não foi possível baixar/converter para MP3 a URL: {url} (Verifique se o FFmpeg está instalado)", 500

    def generate():
        # Stream do arquivo MP3 local
        try:
            with open(final_filepath, 'rb') as f:
                while True:
                    chunk = f.read(131072)
                    if not chunk:
                        break
                    yield chunk
        finally:
            # Limpeza do arquivo temporário
            if os.path.exists(final_filepath):
                os.remove(final_filepath)
                # Tentar limpar o diretório temporário se estiver vazio
                try:
                    os.rmdir(TEMP_DIR)
                except OSError:
                    pass

    return Response(
        generate(),
        # O mimetype correto para MP3
        mimetype="audio/mp3",
        headers={"Content-Disposition": f"attachment; filename={title_with_ext}"}
    )

@app.route("/baixar_playlist")
def baixar_playlist():
    url = request.args.get("url")
    if not url:
        return "URL inválida", 400

    z = zipstream.ZipFile(mode='w', compression=zipstream.ZIP_DEFLATED)

    # Note: Usamos o extrator 'flat' para obter apenas os metadados da playlist.
    ydl_opts = {"quiet": True, "extract_flat": "in_playlist", "cookiefile": COOKIES_FILE}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            entries = info.get("entries", [info])
        except Exception as e:
            print(f"ERRO ao extrair informações da playlist: {e}")
            return "Não foi possível extrair as informações da playlist.", 500


    def fetch_audio(entry):
        video_url = entry.get("url")
        # Faz o download local e a conversão para MP3
        title_with_ext, final_filepath = download_audio_mp3_locally(video_url)
        
        if not final_filepath:
            print(f"ATENÇÃO: Pulando {entry.get('title', 'vídeo sem título')} - Falha na conversão para MP3.")
            return None, None 

        # Retorna o nome do arquivo no ZIP e um iterador do conteúdo do arquivo
        def stream_file():
            try:
                with open(final_filepath, 'rb') as f:
                    while True:
                        chunk = f.read(131072)
                        if not chunk:
                            break
                        yield chunk
            finally:
                # Garante que o arquivo temporário seja apagado após o streaming
                if os.path.exists(final_filepath):
                    os.remove(final_filepath)
                    # Tentar limpar o diretório temporário se estiver vazio
                    try:
                        os.rmdir(TEMP_DIR)
                    except OSError:
                        pass

        return title_with_ext, stream_file()


    # Threads limitadas para não travar o servidor
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = executor.map(fetch_audio, entries)

        for filename, stream_iter in results:
            if filename and stream_iter: # Ignorar resultados None de vídeos ignorados
                z.write_iter(filename, stream_iter)

    return Response(
        z,
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=playlist_mp3.zip"}
    )


if __name__ == "__main__":
    # Limpar o diretório temporário no início, caso existam restos de falhas anteriores
    if os.path.exists(TEMP_DIR):
        try:
            shutil.rmtree(TEMP_DIR)
        except Exception as e:
            print(f"Aviso: Não foi possível limpar o diretório temporário {TEMP_DIR}: {e}")
            
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)