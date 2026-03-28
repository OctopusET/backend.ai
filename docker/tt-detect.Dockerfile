FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir 'tt-smi>=3.1.0,<4'
COPY scripts/tt-detect.py /app/tt-detect.py
CMD ["python", "/app/tt-detect.py"]
