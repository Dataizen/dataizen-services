# Hook HTTP de tusd : enregistre les fichiers déposés (upload résumable) comme
# ressources CKAN. Tourne en root (chown des fichiers déplacés dans le filestore).
FROM python:3.12-slim

WORKDIR /srv/tusd-hook
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
