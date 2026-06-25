FROM python:3.12-slim
RUN addgroup --system app && adduser --system --ingroup app app
WORKDIR /app
COPY bid_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY bid_service/main.py .
USER app
EXPOSE 9400
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9400/health')" || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9400"]