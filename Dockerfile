FROM python:3.11-slim

# Instala o tesseract (necessário para ler o captcha)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia e instala as dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código do bot
COPY main.py .

# Porta do servidor de status
EXPOSE 8000

CMD ["python", "main.py"]
