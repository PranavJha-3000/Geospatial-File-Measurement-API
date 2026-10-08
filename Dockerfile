# pyogrio wheels bundle GDAL binaries, so no system GDAL packages are required.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV DATABASE_URL=sqlite:////data/app.db \
    UPLOAD_DIR=/data/uploads

VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]