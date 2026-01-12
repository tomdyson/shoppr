# Build stage for Tailwind CSS
FROM node:20-slim AS css-builder

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY tailwind.config.js ./
COPY src/ ./src/
COPY index.html ./
RUN npm run build:css

# Runtime stage
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies for WeasyPrint
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY main.py database.py cleanup.py litellm_client.py ./
COPY index.html sw.js manifest.json paris-figure.jpg paris-figure-down.jpg ./
COPY prompts/ ./prompts/
COPY static/ ./static/

# Copy built CSS from builder stage
COPY --from=css-builder /app/dist/ ./dist/

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app

USER appuser

# Set database path for persistence
ENV DB_PATH=/app/data/shopping.db

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
