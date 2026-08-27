FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       texlive-latex-base texlive-latex-extra texlive-fonts-recommended \
       texlive-lang-other poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

ENV PORT=8080
EXPOSE 8080
CMD gunicorn --bind 0.0.0.0:${PORT} --workers 1 --timeout 45 app:app
