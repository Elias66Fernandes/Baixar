# Usa uma imagem base Python oficial (baseada em Debian)
# Esta imagem é leve e contém as ferramentas necessárias.
FROM python:3.11-slim

# Define o diretório de trabalho dentro do container
WORKDIR /app

# 1. Instalação de Dependências do Sistema (FFmpeg)
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 2. Copia os arquivos de requisitos
COPY requirements.txt .

# 3. Instala as dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copia o restante do código da aplicação para o container
COPY . .

# Expõe a porta que o Flask vai usar (5000 por padrão no código)
EXPOSE 5000

# 5. Comando de Execução (Entrypoint)
CMD exec gunicorn --bind 0.0.0.0:$PORT --workers 4 app:app