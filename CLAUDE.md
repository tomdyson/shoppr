# Claude Code Assistant Notes

This file contains important reminders and context for Claude Code when working on this project.

## Project: Shoppr

A mobile-first shopping list app using FastAPI + Vue.js + LiteLLM proxy for AI-powered categorization.

## Deployment Checklist

**IMPORTANT**: Before committing changes that will be deployed to production, verify:

### 1. Dockerfile Updates
- [ ] If you added new Python files, they're automatically included via `COPY *.py ./`
- [ ] If you added new directories, update the Dockerfile `COPY` commands
- [ ] If you changed dependencies, verify `requirements.txt` is copied before `RUN pip install`

### 2. Environment Variables
- [ ] New environment variables are documented in `.env.example`
- [ ] README.md configuration section is updated
- [ ] Consider if the new variables need to be added to deployment platform (e.g., Coolify, Fly.io)

### 3. Dependencies
- [ ] If adding Python packages, update `requirements.txt`
- [ ] If adding Node packages, update `package.json`
- [ ] Verify compatibility with Python 3.13 (runtime version in Dockerfile)

### 4. Database Changes
- [ ] If modifying `database.py` schema, consider migration path for existing production data
- [ ] Test with existing `shopping.db` file to ensure backward compatibility

### 5. Static Assets
- [ ] If adding new images/icons, update Dockerfile copy commands
- [ ] If modifying Tailwind CSS, rebuild with `npm run build:css`
- [ ] Verify `dist/output.css` is generated and copied in Docker build

## Common Pitfalls

### Python Module Not Found in Production
**Symptom**: `ModuleNotFoundError` in production but works locally
**Solution**: Dockerfile now uses `COPY *.py ./` to catch all Python files automatically

### Environment Variable Missing
**Symptom**: `ValueError: LITELLM_API_KEY environment variable is required`
**Solution**: Ensure all required env vars are set in deployment platform

### Cost Tracking Not Working
**Symptom**: Costs show as 0.0 in API responses
**Solution**:
- Verify proxy returns `x-litellm-response-cost` header
- Check proxy authentication is working
- Review logs for "Warning: No cost header in response"

## Architecture Notes

### LLM Integration
- Uses LiteLLM proxy at `https://litellm.co.tomd.org`
- Model names must include provider prefix: `gemini/gemini-2.5-flash-lite`
- Cost tracking via response headers (see `litellm_client.py`)
- Three LLM call sites in `main.py`:
  - `process_items_with_llm()` - Text categorization
  - `ocr_image_with_llm()` - Image OCR (vision API)
  - `process_edit_with_llm()` - Natural language list editing

### Frontend
- Single-page Vue.js 2 app in `index.html`
- PWA with service worker (`sw.js`) for offline support
- Tailwind CSS compiled from `src/input.css` → `dist/output.css`

### Database
- SQLite with two tables: `shopping_lists` and `shopping_items`
- 5-character URL slugs for list sharing
- Automatic cleanup after 28 days (via `cleanup.py`)

## Development Setup

**IMPORTANT**: Always use the virtual environment when running locally or testing:

```bash
# Activate the virtual environment
source .venv/bin/activate

# Verify you're in the venv (should show .venv in path)
which python
```

All local development and testing commands should be run within the activated virtual environment.

## Testing Before Deploy

### Run Automated Tests

Always run the test suite before deploying changes:

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all tests
LITELLM_API_KEY=test pytest test_main.py test_advanced.py -v

# Run specific test
pytest test_main.py::test_api_process_text -v

# Run with coverage (if pytest-cov installed)
pytest test_main.py --cov=main --cov=database
```

The test suite (`test_main.py`) includes 10 critical tests covering:
- Database operations (create, retrieve, update lists and items)
- API endpoints (process text/image, get/edit lists, update items)
- Validation (slug format, supermarket validation)
- Error handling (invalid inputs, 404s, etc.)

The `test_advanced.py` suite adds coverage for:
- PDF generation
- LLM failure modes
- Edge cases

All LLM calls are mocked, so tests run without API costs.

### Manual Testing

```bash
# Local testing (remember to activate .venv first!)
source .venv/bin/activate
uvicorn main:app --reload

# Docker testing
docker compose build
docker compose up -d
docker compose logs -f

# Test endpoints
curl -X POST http://localhost:8000/api/process \
  -H "Content-Type: application/json" \
  -d '{"text": "milk\nbread\neggs", "supermarket": "tesco"}'
```

## Commit Message Format

Follow existing conventions:
- First line: Brief imperative summary (e.g., "Add feature X", "Fix bug Y")
- Include "Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
- Describe the "why" not just the "what"

## Useful Commands

```bash
# Run with Just task runner
just run          # Start dev server
just build-css    # Build Tailwind CSS
just watch-css    # Watch CSS changes
just docker-build # Build Docker image
just format       # Format with Black
just lint         # Lint with Pylint

# Manual commands
uvicorn main:app --reload
npm run build:css
npm run watch:css
```

## Repository
- Main branch: `main`
- Remote: https://github.com/tomdyson/shoppr.git

## Deployment

**IMPORTANT**: Pushing to `main` automatically deploys to production via Coolify.

- **Production URL**: https://shop.tomd.org
- **Platform**: Coolify
- **Trigger**: Automatic on push to `main` branch

Before pushing to main, ensure you've completed the [Deployment Checklist](#deployment-checklist) above.
