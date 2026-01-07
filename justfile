# Install Python dependencies
install:
    pip install -r requirements.txt

# Install Node dependencies
install-node:
    npm install

# Build CSS
build-css:
    npm run build:css

# Watch CSS for development
watch-css:
    npm run watch:css

# Run the development server
run:
    uvicorn main:app --reload

# Run with CSS watching (in separate terminal)
dev:
    @echo "Run 'just watch-css' in another terminal"
    uvicorn main:app --reload

# Format Python code
format:
    black .

# Lint Python code
lint:
    pylint main.py database.py

# Build Docker image
docker-build:
    docker compose build

# Run with Docker
docker-run:
    docker compose up

# Clean generated files
clean:
    rm -rf dist/ node_modules/ __pycache__/ *.db
