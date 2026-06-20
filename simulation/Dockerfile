FROM python:3.12-slim
RUN addgroup --system app && adduser --system --ingroup app app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER app
EXPOSE 9100
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9100/health')" || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9100"]
