# Shoppr

A mobile-first web app that turns messy shopping lists into organized, store-optimized checklists. Paste text, snap a photo, or upload a screenshot — Shoppr uses AI to categorize your items and order them by supermarket layout, making your shopping trip as efficient as possible.

## Features

- **Multiple input methods**: Type, paste text, upload images, take photos, or paste screenshots
- **Smart OCR**: Extracts items from handwritten lists, photos, and screenshots using vision AI
- **Automatic categorization**: Groups items by store area (produce, dairy, frozen, etc.)
- **Store-specific ordering**: Orders items by typical supermarket layout for 8 UK stores
- **Touch-friendly UI**: Mobile-first design with large tap targets and sticky headers
- **Shareable lists**: Short 5-character URLs for easy sharing (e.g., `/a3x9k`)
- **Progress tracking**: Visual progress bar and item counts
- **PWA support**: Install on your phone, works offline for saved lists
- **No account required**: Just create and share lists

## Supported Supermarkets

- Tesco
- Sainsbury's
- Asda
- Morrisons
- Aldi
- Lidl
- Waitrose
- M&S

Each supermarket has a custom prompt defining its typical store layout, so items are ordered in the sequence you'd encounter them while shopping.

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI (Python) |
| Frontend | Vue.js 2 (CDN) |
| Styling | Tailwind CSS |
| Database | SQLite |
| LLM | Gemini via LiteLLM Proxy |
| Deployment | Docker |

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for Tailwind CSS build)
- Access to a LiteLLM proxy with API key (or set up your own)

### Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd shoppr

# Install Python dependencies
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Install Node dependencies and build CSS
npm install
npm run build:css

# Configure environment
cp .env.example .env
# Edit .env with your API key
```

### Configuration

Edit `.env` with your settings:

```env
# LLM Configuration - LiteLLM Proxy
LITELLM_PROXY_URL=https://litellm.co.tomd.org
LITELLM_API_KEY=your-litellm-proxy-key-here
LITELLM_MODEL_PREFIX=gemini/       # Provider prefix (optional, set to "" if using full names)
LLM_MODEL=gemini/gemini-2.5-flash-lite    # Model for categorization
LLM_VISION_MODEL=gemini/gemini-2.5-flash  # Model for OCR (must support vision)

# Database
DB_PATH=shopping.db
```

#### LiteLLM Proxy Setup

The app uses a [LiteLLM proxy](https://docs.litellm.ai/docs/proxy/quick_start) for LLM requests, which provides:

- **Unified API**: Single interface for multiple LLM providers (OpenAI, Anthropic, Google, etc.)
- **Automatic cost tracking**: Costs tracked via response headers
- **Request logging**: Monitor usage and debugging
- **Load balancing**: Distribute requests across providers

**Model Naming**: Model names should include the provider prefix (e.g., `gemini/gemini-2.5-flash-lite`) to match your proxy configuration. The `LITELLM_MODEL_PREFIX` setting can automatically add the prefix if you use short names.

Set up your own proxy or use an existing one. The proxy handles provider-specific API keys and routing.

### Running the App

```bash
source .venv/bin/activate
uvicorn main:app --reload
```

Open http://localhost:8000 in your browser.

## Usage

### Creating a Shopping List

1. **Select a supermarket** (optional) — Choose your store for optimized ordering
2. **Add items** via one of these methods:
   - **Type or paste** a list in the text area
   - **Upload an image** of a handwritten or printed list
   - **Take a photo** (on mobile) using the camera button
   - **Paste a screenshot** using Ctrl+V or the Paste button
3. **Click "Create shopping list"** — The AI processes your input and creates an organized list

### Using Your List

- **Check off items** as you shop by tapping the checkbox or the item row
- **Track progress** with the visual progress bar
- **Share your list** by clicking Share and sending the URL to family members
- **Start fresh** with the "New list" button

### Tips for Best Results

- For text input, one item per line works best
- Include quantities: "Milk 2L", "6 eggs", "Chicken 500g"
- For photos, ensure good lighting and readable text
- The app handles both printed and handwritten lists

## API Reference

### Process Text

```http
POST /api/process
Content-Type: application/json

{
  "text": "Milk 2L\nBread\nEggs\nBananas",
  "supermarket": "tesco"  // optional
}
```

### Process Image

```http
POST /api/process-image
Content-Type: application/json

{
  "image": "data:image/png;base64,...",  // Base64 encoded image
  "supermarket": "sainsburys"  // optional
}
```

### Get Shopping List

```http
GET /api/list/{list_id}
```

### Update Item Status

```http
PUT /api/list/{list_id}/item/{item_id}
Content-Type: application/json

{
  "checked": true
}
```

### Response Format

```json
{
  "list_id": "a3x9k",
  "supermarket": "tesco",
  "supermarket_display": "Tesco",
  "groups": [
    {
      "area": "produce",
      "area_display": "Fruit & Veg",
      "items": [
        {
          "id": 1,
          "name": "Bananas",
          "quantity": "6",
          "checked": false
        }
      ]
    }
  ]
}
```

## Development

### Available Commands

Using [just](https://github.com/casey/just):

```bash
just install       # Install Python dependencies
just install-node  # Install Node dependencies
just build-css     # Build Tailwind CSS (production)
just watch-css     # Watch CSS for development
just run           # Run development server
just format        # Format code with Black
just lint          # Lint with Pylint
just docker-build  # Build Docker image
just docker-run    # Run with Docker Compose
just clean         # Remove generated files
```

Or manually:

```bash
# Development server with hot reload
uvicorn main:app --reload

# Watch CSS changes (in separate terminal)
npm run watch:css

# Build production CSS
npm run build:css
```

### Project Structure

```
shoppr/
├── main.py                 # FastAPI application
├── database.py             # SQLite database layer
├── cleanup.py              # Scheduled cleanup script
├── index.html              # Vue.js 2 single-page app
├── requirements.txt        # Python dependencies
├── package.json            # Node dependencies (Tailwind)
├── tailwind.config.js      # Tailwind configuration
├── src/
│   └── input.css           # Tailwind source
├── dist/
│   └── output.css          # Compiled CSS (generated)
├── prompts/                 # Supermarket layout prompts
│   ├── generic.md          # Default layout
│   ├── tesco.md
│   ├── sainsburys.md
│   ├── asda.md
│   ├── morrisons.md
│   ├── aldi.md
│   ├── lidl.md
│   ├── waitrose.md
│   └── ms.md
├── static/                  # Static assets
│   ├── icon-192.png        # PWA icon (add your own)
│   └── icon-512.png        # PWA icon (add your own)
├── manifest.json           # PWA manifest
├── sw.js                   # Service worker
├── Dockerfile              # Multi-stage Docker build
├── docker-compose.yaml     # Docker Compose config
├── justfile                # Development commands
├── .env                    # Environment variables (not in git)
└── .env.example            # Environment template
```

## Customizing Supermarket Layouts

Each supermarket has a prompt file in the `prompts/` directory that defines:

1. **Store areas** (produce, dairy, frozen, etc.)
2. **Area ordering** (the sequence you'd walk through the store)
3. **Categorization hints** (what items belong in each area)

### Example: `prompts/tesco.md`

```markdown
# Tesco Store Layout

Organize items into these areas, ordered by typical Tesco layout:

1. **produce** (area_order: 1) - Fresh fruits, vegetables
2. **bakery** (area_order: 2) - Bread, pastries
3. **dairy** (area_order: 3) - Milk, cheese, eggs
...
```

To customize for your local store:

1. Copy an existing prompt file
2. Adjust the area ordering based on your store's layout
3. Add any store-specific notes or categories

## Docker Deployment

### Build and Run

```bash
# Build the image
docker compose build

# Run the container
docker compose up -d

# View logs
docker compose logs -f
```

### Environment Variables

Pass your API key via `.env` file or environment:

```bash
docker compose up -d
# .env file is mounted automatically
```

### Persistent Data

Shopping lists are stored in a Docker volume (`shopping_data`) that persists across container restarts.

### Scheduled Cleanup

Shopping lists are automatically deleted after 28 days. Schedule the cleanup script via cron or your deployment platform:

```bash
# Run daily at 3am
0 3 * * * python /app/cleanup.py
```

In Coolify, add this as a scheduled task pointing to `python /app/cleanup.py`.

## PWA Installation

### On Mobile (iOS/Android)

1. Open the app in your browser
2. Tap the browser menu (⋮ or Share)
3. Select "Add to Home Screen"
4. The app icon will appear on your home screen

### PWA Icons

Add your own icons to the `static/` directory:

- `icon-192.png` (192×192 pixels)
- `icon-512.png` (512×512 pixels)

## Troubleshooting

### "Failed to parse LLM response"

The LLM returned invalid JSON. This can happen with:
- Very long or complex lists
- Unusual item names
- Rate limiting

Try again or use a more capable model.

### "Could not extract text from image"

The vision model couldn't read your image. Try:
- Better lighting
- Clearer handwriting
- Higher resolution image
- Cropping to just the list

### Images not uploading

Check that:
- The image is under 10MB
- It's a supported format (PNG, JPG, WebP)
- Your browser supports the Clipboard API (for paste)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run `just format` and `just lint`
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- LLM integration via [LiteLLM Proxy](https://docs.litellm.ai/)
- Styled with [Tailwind CSS](https://tailwindcss.com/)
- Frontend powered by [Vue.js](https://vuejs.org/)
