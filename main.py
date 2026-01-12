import base64
import json
import os
import re
import time
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
import llm
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from weasyprint import HTML

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
    updated_at: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class UpdateItemRequest(BaseModel):
    checked: bool


class EditListRequest(BaseModel):
    text: str  # Natural language edit instructions


class EditListResponse(BaseModel):
    list_id: str
    supermarket: Optional[str]
    supermarket_display: Optional[str]
    groups: List[ItemGroup]
    changes: Dict[str, List[str]]  # {added: [], removed: [], kept: []}
    updated_at: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class ListVersionResponse(BaseModel):
    updated_at: Optional[str]


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


def process_edit_with_llm(
    existing_items: List[dict],
    edit_text: str,
    supermarket: Optional[str]
) -> Tuple[List[dict], Dict[str, List[str]], Dict[str, Any]]:
    """
    Process edit instructions to modify an existing shopping list.

    Args:
        existing_items: Current items in the list
        edit_text: Natural language edit instructions
        supermarket: The supermarket for categorization

    Returns:
        Tuple of (new_items, changes_dict, usage_stats)
    """
    model = llm.get_model(MODEL_NAME)
    if API_KEY:
        model.key = API_KEY

    store_layout = load_prompt(supermarket)

    # Format existing items for the prompt
    existing_list = "\n".join([
        f"- {item['name']}" + (f" ({item['quantity']})" if item.get('quantity') else "")
        for item in existing_items
    ])

    system_prompt = f"""You are a shopping list editor. You will receive a current shopping list and edit instructions.
Apply the edit instructions to modify the list.

{store_layout}

INSTRUCTIONS FOR EDITING:
- "add X" or just "X" means add item X to the list
- "remove X" or "delete X" means remove item X
- "change X to Y" or "replace X with Y" means replace item X with Y
- You can interpret natural language like "I don't need the apples anymore" as "remove apples"
- Be smart about matching items - "remove milk" should remove "Semi-skimmed milk" if that's what's in the list
- Keep all existing items that weren't explicitly removed or changed

Respond with a JSON object containing:
1. "items": Array of all items in the updated list (same format as before)
2. "added": Array of item names that were newly added
3. "removed": Array of item names that were removed
4. "kept": Array of item names that were kept unchanged

Each item in the "items" array must have:
- "name": Item name (cleaned up, standardized)
- "quantity": Quantity if specified (e.g., "2", "500g"), null if not specified
- "area": Category key from the layout above (e.g., "dairy", "produce")
- "area_order": Number from the layout order above

Example response:
{{
    "items": [
        {{"name": "Semi-skimmed milk", "quantity": "2L", "area": "dairy", "area_order": 3}},
        {{"name": "Salmon fillets", "quantity": "400g", "area": "meat", "area_order": 4}}
    ],
    "added": ["Salmon fillets"],
    "removed": ["Bananas"],
    "kept": ["Semi-skimmed milk"]
}}

IMPORTANT: Respond ONLY with the JSON object, no additional text."""

    user_prompt = f"""CURRENT LIST:
{existing_list}

EDIT INSTRUCTIONS:
{edit_text}"""

    response = model.prompt(user_prompt, system=system_prompt)

    # Log token usage
    print(f"Edit model used: {MODEL_NAME}")
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
    print("Raw LLM edit response:", raw_response)

    cleaned_response = strip_markdown_code_blocks(raw_response)
    result = json.loads(cleaned_response)

    # Validate structure of LLM JSON response
    if not isinstance(result, dict):
        raise ValueError("LLM edit response must be a JSON object")

    if "items" not in result:
        raise ValueError("LLM edit response is missing required 'items' field")

    items = result["items"]
    if not isinstance(items, list):
        raise ValueError("LLM edit response field 'items' must be a list")

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"LLM edit response 'items[{index}]' must be a JSON object")

    changes: Dict[str, List[Any]] = {}
    for key in ("added", "removed", "kept"):
        value = result.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"LLM edit response field '{key}' must be a list")
        changes[key] = value
    return items, changes, usage_stats


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


@app.get("/api/list/{list_id}/version", response_model=ListVersionResponse)
async def get_list_version(list_id: str):
    """Get the current version (updated_at) of a list for polling."""
    if not is_valid_slug(list_id):
        raise HTTPException(status_code=400, detail="Invalid list ID format")

    updated_at = database.get_list_version(list_id)
    if updated_at is None:
        raise HTTPException(status_code=404, detail="List not found")

    return ListVersionResponse(updated_at=updated_at)


@app.post("/api/list/{list_id}/edit", response_model=EditListResponse)
async def edit_list(list_id: str, request: EditListRequest):
    """Edit an existing shopping list using natural language instructions."""
    if not is_valid_slug(list_id):
        raise HTTPException(status_code=400, detail="Invalid list ID format")

    try:
        # Get the existing list
        list_data = database.get_shopping_list(list_id)
        if list_data is None:
            raise HTTPException(status_code=404, detail="List not found")

        # Flatten existing items from groups
        existing_items = []
        for group in list_data['groups']:
            for item in group['items']:
                existing_items.append({
                    'name': item['name'],
                    'quantity': item.get('quantity')
                })

        # Process edit instructions with LLM
        new_items, changes, edit_usage = process_edit_with_llm(
            existing_items,
            request.text,
            list_data['supermarket']
        )

        # Validate new items
        if not isinstance(new_items, list):
            raise HTTPException(status_code=500, detail="Invalid response from LLM")

        for item in new_items:
            if not all(k in item for k in ("name", "area", "area_order")):
                raise HTTPException(status_code=500, detail="Invalid item format from LLM")

        # Update the database
        if not database.update_shopping_list(list_id, new_items, changes):
            raise HTTPException(status_code=500, detail="Failed to update list")

        # Get the updated list
        updated_list = database.get_shopping_list(list_id)

        # Format response
        groups = []
        for group in updated_list['groups']:
            area_display = AREA_DISPLAY_NAMES.get(group['area'], group['area'].title())
            groups.append(ItemGroup(
                area=group['area'],
                area_display=area_display,
                items=[ShoppingItem(**item) for item in group['items']]
            ))

        supermarket_display = None
        if updated_list['supermarket']:
            supermarket_display = SUPERMARKETS.get(updated_list['supermarket'])

        return EditListResponse(
            list_id=list_id,
            supermarket=updated_list['supermarket'],
            supermarket_display=supermarket_display,
            groups=groups,
            changes=changes,
            updated_at=updated_list.get('updated_at'),
            meta={"edit": edit_usage}
        )

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse LLM response: {str(e)}")
    except Exception as e:
        print(f"Error editing list: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error editing list: {str(e)}")


@app.get("/{list_id}.pdf")
def get_list_pdf(request: Request, list_id: str):
    """Generate and return a PDF for the shopping list."""
    if not is_valid_slug(list_id):
        raise HTTPException(status_code=400, detail="Invalid list ID format")

    list_data = database.get_shopping_list(list_id)
    if list_data is None:
        raise HTTPException(status_code=404, detail="Shopping list not found")

    # Generate HTML for PDF
    base_url = str(request.base_url).rstrip('/')
    html_content = generate_pdf_html(list_data, base_url)

    # Generate PDF
    pdf_bytes = HTML(string=html_content).write_pdf()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={list_id}.pdf"}
    )


def generate_pdf_html(list_data: dict, base_url: str) -> str:
    """Generate HTML for the PDF shopping list."""
    groups = []
    for group in list_data['groups']:
        area_display = AREA_DISPLAY_NAMES.get(group['area'], group['area'].title())
        groups.append({
            "area_display": area_display,
            "items": group['items']
        })

    supermarket_display = SUPERMARKETS.get(list_data['supermarket']) if list_data['supermarket'] else "Shopping List"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Shopping List</title>
        <style>
            @page {{
                size: A4;
                margin: 2cm;
            }}
            body {{
                font-family: sans-serif;
                font-size: 12pt;
                color: #333;
                line-height: 1.5;
            }}
            h1 {{
                font-size: 18pt;
                margin-bottom: 0.5cm;
                color: #000;
                border-bottom: 2px solid #000;
                padding-bottom: 0.2cm;
            }}
            .group {{
                margin-bottom: 1cm;
                page-break-inside: avoid;
            }}
            .group-header {{
                font-weight: bold;
                font-size: 14pt;
                margin-bottom: 0.3cm;
                color: #444;
                text-transform: uppercase;
                border-bottom: 1px solid #ccc;
            }}
            .item {{
                display: flex;
                align-items: center;
                margin-bottom: 0.2cm;
            }}
            .checkbox {{
                display: inline-block;
                width: 12px;
                height: 12px;
                border: 1px solid #000;
                margin-right: 10px;
            }}
            .checkbox.checked {{
                background-color: #ddd;
                position: relative;
            }}
            .checkbox.checked::after {{
                content: '';
                position: absolute;
                left: 3px;
                top: 3px;
                width: 6px;
                height: 6px;
                background-color: #000;
            }}
            .item-text {{
                flex: 1;
            }}
            .item-text.checked {{
                text-decoration: line-through;
                color: #888;
            }}
            .quantity {{
                color: #666;
                font-size: 0.9em;
                margin-left: 5px;
            }}
            .footer {{
                position: fixed;
                bottom: 0;
                left: 0;
                right: 0;
                text-align: center;
                font-size: 9pt;
                color: #999;
                border-top: 1px solid #eee;
                padding-top: 0.5cm;
            }}
        </style>
    </head>
    <body>
        <h1>{supermarket_display}</h1>
    """

    for group in groups:
        if not group['items']:
            continue

        html += f"""
        <div class="group">
            <div class="group-header">{group['area_display']}</div>
        """

        for item in group['items']:
            checked_class = " checked" if item['checked'] else ""
            quantity_html = f'<span class="quantity">({item["quantity"]})</span>' if item.get('quantity') else ''

            html += f"""
            <div class="item">
                <div class="checkbox{checked_class}"></div>
                <div class="item-text{checked_class}">
                    {item['name']}{quantity_html}
                </div>
            </div>
            """

        html += "</div>"

    # Add footer with URL
    list_url = f"{base_url}/{list_data['list_id']}"

    html += f"""
        <div class="footer">
            List: {list_url}
        </div>
    </body>
    </html>
    """

    return html


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
        updated_at=list_data.get('updated_at'),
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
