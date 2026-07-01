FROM python:3.12-slim
RUN addgroup --system app && adduser --system --ingroup app app
WORKDIR /app
COPY agent_launcher/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared/ ./shared/
COPY agent_launcher/main.py .
USER app
EXPOSE 9901
CMD ["python", "-u", "main.py", "--type", "bidder", "--registry", "http://agent-registry:9900"]