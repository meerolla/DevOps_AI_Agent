FROM python:3.12-slim AS base
WORKDIR /app
RUN useradd -m appuser
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS test
RUN pip install --no-cache-dir pytest
COPY . /app

FROM base AS runtime
COPY . /app
USER appuser
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
