FROM python:3.10-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
COPY pyproject.toml ./
COPY constraints.txt ./
COPY src ./src
RUN pip install --no-cache-dir -c constraints.txt . && useradd --create-home engine && mkdir /data && chown engine:engine /data
USER engine
CMD ["uvicorn", "math_engine.services.compute:app", "--host", "0.0.0.0", "--port", "8000"]
