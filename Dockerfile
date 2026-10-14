FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY web ./web
RUN pip install --no-cache-dir -e .
ENV PORT=8000 CITEGAP_DB=/data/citegap.db
VOLUME /data
EXPOSE 8000
# keys come from the platform's environment (TINYFISH_API_KEY, optional ANTHROPIC_API_KEY); never baked into the image
CMD ["sh", "-c", "uvicorn citegap.api:app_factory --factory --host 0.0.0.0 --port ${PORT}"]
