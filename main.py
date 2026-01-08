import base64
import json
import os
import re
import time
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
import llm
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database

# Get the directory where main.py is located
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from .env file
load_dotenv(BASE_DIR / ".env", override=True)

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get environment variables
MODEL_NAME = os.getenv("LLM_MODEL", "gemini-2.5-flash-lite")
VISION_MODEL_NAME = os.getenv("LLM_VISION_MODEL", "gemini-2.5-flash")
API_KEY = os.getenv("LLM_API_KEY")

# Pricing per 1M tokens (USD)
# Users can update this dictionary to reflect current pricing or add new models
MODEL_PRICING = {
    "gemini-2.5-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    # Fallback default
    "default": {"input": 0.10, "output": 0.40}
}

# Supermarket options
SUPERMARKETS = {
    "tesco": "Tesco",
    "sainsburys": "Sainsbury's",
    "asda": "Asda",
    "morrisons": "Morrisons",
    "aldi": "Aldi",
    "lidl": "Lidl",
    "waitrose": "Waitrose",
    "ms": "M&S",
}

# Area display names
AREA_DISPLAY_NAMES = {
    "produce": "Fruit & Veg",
    "bakery": "Bakery",
    "dairy": "Dairy & Eggs",
    "meat": "Meat & Fish",
    "deli": "Deli",
    "frozen": "Frozen",
    "pantry": "Pantry",
    "breakfast": "Breakfast",
    "snacks": "Snacks",
    "confectionery": "Confectionery",
    "drinks": "Drinks",
    "tea_coffee": "Tea & Coffee",
    "alcohol": "Alcohol",
    "household": "Household",
    "health_beauty": "Health & Beauty",
    "baby": "Baby",
    "pet": "Pet",
    "world_foods": "World Foods",
    "other": "Other",
}


# Pydantic models
class ProcessTextRequest(BaseModel):
    text: str
    supermarket: Optional[str] = None


class ProcessImageRequest(BaseModel):
    image: str  # Base64-encoded image
    supermarket: Optional[str] = None


class ShoppingItem(BaseModel):
    id: int
    name: str
    quantity: Optional[str] = None
    checked: bool = False


class ItemGroup(BaseModel):
    area: str
    area_display: str
    items: List[ShoppingItem]


class ShoppingListResponse(BaseModel):
    list_id: str
    supermarket: Optional[str]
    supermarket_display: Optional[str]
    groups: List[ItemGroup]
    meta: Optional[Dict[str, Any]] = None


class UpdateItemRequest(BaseModel):
    checked: bool


def strip_markdown_code_blocks(text: str) -> str:
    """Remove markdown code blocks from text."""
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()


def is_valid_slug(slug: str) -> bool:
    """Check if slug is a valid 5-character alphanumeric string."""
    return bool(re.match(r'^[a-z0-9]{5}$', slug))


def load_prompt(supermarket: Optional[str]) -> str:
    """Load the appropriate supermarket prompt file."""
    prompt_name = supermarket if supermarket and supermarket in SUPERMARKETS else "generic"
    prompt_path = BASE_DIR / "prompts" / f"{prompt_name}.md"

    if not prompt_path.exists():
        prompt_path = BASE_DIR / "prompts" / "generic.md"

    with open(prompt_path, 'r') as f:
        return f.read()


def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for the given usage."""
    pricing = MODEL_PRICING.get(model_name, MODEL_PRICING.get("default"))
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return input_cost + output_cost


def process_items_with_llm(items_text: str, supermarket: Optional[str]) -> Tuple[List[dict], Dict[str, Any]]:
    """Process shopping list text into categorized items using LLM."""
    model = llm.get_model(MODEL_NAME)
    if API_KEY:
        model.key = API_KEY

    store_layout = load_prompt(supermarket)

    system_prompt = f"""You are a shopping list organizer. Parse the input into a structured list.

{store_layout}

Respond with a JSON array. Each item must have:
- "name": Item name (cleaned up, standardized - e.g., "Semi-skimmed milk" not "milk semi skimmed")
- "quantity": Quantity if specified (e.g., "2", "500g", "x3"), null if not specified
- "area": Category key from the layout above (e.g., "dairy", "produce")
- "area_order": Number from the layout order above

Example output:
[
    {{"name": "Semi-skimmed milk", "quantity": "2L", "area": "dairy", "area_order": 3}},
    {{"name": "Bananas", "quantity": "6", "area": "produce", "area_order": 1}}
]

IMPORTANT: Respond ONLY with the JSON array, no additional text."""

    response = model.prompt(items_text, system=system_prompt)

    # Log token usage
    print(f"Model used: {MODEL_NAME}")
    usage_stats = {
        "model": MODEL_NAME,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost": 0.0
    }

    usage = response.usage()
    if usage:
        print(f"Token count - Input: {usage.input}, Output: {usage.output}")
        usage_stats["input_tokens"] = usage.input
        usage_stats["output_tokens"] = usage.output
        usage_stats["cost"] = calculate_cost(MODEL_NAME, usage.input, usage.output)

    raw_response = response.text()
    print("Raw LLM response:", raw_response)

    cleaned_response = strip_markdown_code_blocks(raw_response)
    return json.loads(cleaned_response), usage_stats


def ocr_image_with_llm(image_base64: str) -> Tuple[str, Dict[str, Any]]:
    """Extract text from image using vision-capable LLM."""
    model = llm.get_model(VISION_MODEL_NAME)
    if API_KEY:
        model.key = API_KEY

    # Decode base64 to bytes
    # Handle data URL format (e.g., "data:image/png;base64,...")
    if ',' in image_base64:
        image_base64 = image_base64.split(',')[1]

    image_bytes = base64.b64decode(image_base64)

    response = model.prompt(
        "Extract all text from this shopping list image. "
        "Return only the items, one per line. "
        "Include quantities if visible. "
        "Do not add any commentary or formatting.",
        attachments=[llm.Attachment(content=image_bytes, type="image/png")]
    )

    # Log token usage
    print(f"Vision model used: {VISION_MODEL_NAME}")
    usage_stats = {
        "model": VISION_MODEL_NAME,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost": 0.0
    }

    usage = response.usage()
    if usage:
        print(f"Token count - Input: {usage.input}, Output: {usage.output}")
        usage_stats["input_tokens"] = usage.input
        usage_stats["output_tokens"] = usage.output
        usage_stats["cost"] = calculate_cost(VISION_MODEL_NAME, usage.input, usage.output)

    return response.text(), usage_stats


# Initialize the database when the app starts
@app.on_event("startup")
async def startup_event():
    time.sleep(2)  # Allow volume mounting in Docker
    print(f"Starting application with database path: {os.getenv('DB_PATH', 'shopping.db')}")
    database.init_db()


# Serve index.html at root
@app.get("/")
async def read_root():
    return FileResponse(BASE_DIR / "index.html")


# Mount static directories
app.mount("/dist", StaticFiles(directory=BASE_DIR / "dist"), name="dist")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


# Serve static images
@app.get("/paris-figure.jpg")
async def paris_figure():
    return FileResponse(BASE_DIR / "paris-figure.jpg")


@app.get("/paris-figure-down.jpg")
async def paris_figure_down():
    return FileResponse(BASE_DIR / "paris-figure-down.jpg")


# Serve PWA files
@app.get("/manifest.json")
async def manifest():
    return FileResponse(BASE_DIR / "manifest.json")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(BASE_DIR / "sw.js", media_type="application/javascript")


# API endpoints
@app.post("/api/process", response_model=ShoppingListResponse)
async def process_text(request: ProcessTextRequest):
    """Process text input into a categorized shopping list."""
    try:
        # Validate supermarket if provided
        if request.supermarket and request.supermarket not in SUPERMARKETS:
            raise HTTPException(status_code=400, detail="Invalid supermarket")

        # Process with LLM
        items, planning_usage = process_items_with_llm(request.text, request.supermarket)

        # Validate items
        if not isinstance(items, list) or len(items) == 0:
            raise HTTPException(status_code=500, detail="No items found in input")

        for item in items:
            if not all(k in item for k in ("name", "area", "area_order")):
                raise HTTPException(status_code=500, detail="Invalid item format from LLM")

        # Save to database
        list_id = database.create_shopping_list(items, request.supermarket)

        # Get the formatted response
        list_data = database.get_shopping_list(list_id)

        response = format_list_response(list_data)
        response.meta = {
            "planning": planning_usage
        }
        return response

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse LLM response: {str(e)}")
    except Exception as e:
        print(f"Error processing text: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")


@app.post("/api/process-image", response_model=ShoppingListResponse)
async def process_image(request: ProcessImageRequest):
    """Process image input (OCR + categorization) into a shopping list."""
    try:
        # Validate supermarket if provided
        if request.supermarket and request.supermarket not in SUPERMARKETS:
            raise HTTPException(status_code=400, detail="Invalid supermarket")

        # OCR the image
        print("Starting OCR...")
        extracted_text, ocr_usage = ocr_image_with_llm(request.image)
        print(f"OCR result: {extracted_text}")

        if not extracted_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract any text from image")

        # Process the extracted text
        items, planning_usage = process_items_with_llm(extracted_text, request.supermarket)

        # Validate items
        if not isinstance(items, list) or len(items) == 0:
            raise HTTPException(status_code=500, detail="No items found in image")

        for item in items:
            if not all(k in item for k in ("name", "area", "area_order")):
                raise HTTPException(status_code=500, detail="Invalid item format from LLM")

        # Save to database
        list_id = database.create_shopping_list(items, request.supermarket)

        # Get the formatted response
        list_data = database.get_shopping_list(list_id)

        response = format_list_response(list_data)
        response.meta = {
            "ocr": ocr_usage,
            "planning": planning_usage
        }
        return response

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse LLM response: {str(e)}")
    except Exception as e:
        print(f"Error processing image: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")


@app.get("/api/list/{list_id}", response_model=ShoppingListResponse)
async def get_list(list_id: str):
    """Get a shopping list by ID."""
    if not is_valid_slug(list_id):
        raise HTTPException(status_code=400, detail="Invalid list ID format")

    list_data = database.get_shopping_list(list_id)
    if list_data is None:
        raise HTTPException(status_code=404, detail="Shopping list not found")

    return format_list_response(list_data)


@app.put("/api/list/{list_id}/item/{item_id}")
async def update_item(list_id: str, item_id: int, request: UpdateItemRequest):
    """Update the checked status of an item."""
    if not is_valid_slug(list_id):
        raise HTTPException(status_code=400, detail="Invalid list ID format")

    if not database.update_item_status(list_id, item_id, request.checked):
        raise HTTPException(status_code=404, detail="Item not found")

    return {"success": True}


def format_list_response(list_data: dict) -> ShoppingListResponse:
    """Format database response into API response model."""
    groups = []
    for group in list_data['groups']:
        area_display = AREA_DISPLAY_NAMES.get(group['area'], group['area'].title())
        groups.append(ItemGroup(
            area=group['area'],
            area_display=area_display,
            items=[ShoppingItem(**item) for item in group['items']]
        ))

    supermarket_display = None
    if list_data['supermarket']:
        supermarket_display = SUPERMARKETS.get(list_data['supermarket'])

    return ShoppingListResponse(
        list_id=list_data['list_id'],
        supermarket=list_data['supermarket'],
        supermarket_display=supermarket_display,
        groups=groups,
        meta=None  # Explicitly set meta to None by default
    )


# Catch-all route for short list URLs (must be last to avoid catching other routes)
@app.get("/{list_id}")
async def list_page(list_id: str):
    """Serve index.html for valid 5-char list slugs."""
    if not is_valid_slug(list_id):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(BASE_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
