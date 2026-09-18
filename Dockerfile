FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN pip install --no-cache-dir uv
COPY pyproject.toml README.md ./
COPY src ./src
RUN uv pip install --system .

RUN useradd --create-home --uid 10001 whisp && mkdir -p /data && chown whisp:whisp /data
USER whisp
VOLUME ["/data"]
EXPOSE 8080
CMD ["whisp", "serve", "--host", "0.0.0.0", "--port", "8080"]

