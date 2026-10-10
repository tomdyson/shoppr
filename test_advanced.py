
"""
Advanced tests for Shoppr application.
Covers PDF generation, error handling, and edge cases.
"""

import json
import os
import sqlite3
import tempfile
from unittest.mock import Mock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

import database
import main
from main import ListEventBroker, app, format_sse_event, strip_markdown_code_blocks


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    temp_fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_fd)

    # Set the database path
    original_db_path = database.DB_PATH
    database.DB_PATH = temp_path
    database.init_db()

    yield temp_path

    # Cleanup
    database.DB_PATH = original_db_path
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture
def mock_list_data():
    """Mock shopping list data."""
    return [
        {
            "name": "Test Item",
            "quantity": "1",
            "area": "produce",
            "area_order": 1
        }
    ]


# --- Utility Function Tests ---

def test_strip_markdown_code_blocks():
    """Test the markdown stripping utility."""
    # Test standard json block
    text = "```json\n{\"foo\": \"bar\"}\n```"
    assert strip_markdown_code_blocks(text) == '{"foo": "bar"}'

    # Test generic code block
    text = "```\nItem 1\nItem 2\n```"
    assert strip_markdown_code_blocks(text) == "Item 1\nItem 2"

    # Test no markdown
    text = "Just some text"
    assert strip_markdown_code_blocks(text) == "Just some text"

    # Test surrounding text (should keep it? Logic implies it strips the blocks)
    # The current regex `re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)`
    # removes the opening tag, and `re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)`
    # removes the closing tag. It keeps the content inside.
    text = "Here is valid json:\n```json\n[]\n```"
    # Note: the regex is anchored with ^ and $ but MULTILINE.
    # Let's verify exact behavior.
    # If the regex wraps entire lines or just the markers.
    # ^``` matches start of line ` ``` `.
    assert "[]" in strip_markdown_code_blocks(text)


# --- PDF Generation Tests ---

def test_pdf_generation(client, temp_db, mock_list_data):
    """Test PDF generation endpoint."""
    # Create list
    list_id = database.create_shopping_list(mock_list_data, "tesco")

    # Mock weasyprint to avoid actual PDF generation dep
    with patch("main.HTML") as mock_html:
        mock_html_instance = Mock()
        mock_html.return_value = mock_html_instance
        mock_html_instance.write_pdf.return_value = b"%PDF-1.4 mock content"

        response = client.get(f"/{list_id}.pdf")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert f"filename={list_id}.pdf" in response.headers["content-disposition"]
        assert response.content == b"%PDF-1.4 mock content"
        
        # Verify HTML was constructed (mock_html called with string=...)
        mock_html.assert_called_once()
        call_kwargs = mock_html.call_args[1]
        assert "string" in call_kwargs
        assert "Test Item" in call_kwargs["string"]
        assert "Tesco" in call_kwargs["string"]


def test_pdf_not_found(client, temp_db):
    """Test PDF for non-existent list."""
    response = client.get("/abcde.pdf")
    assert response.status_code == 404


def test_pdf_invalid_id(client):
    """Test PDF with invalid ID format."""
    response = client.get("/invalid_id.pdf")
    assert response.status_code == 400


# --- LLM Error Handling Tests ---

def test_llm_failure_process(client, temp_db):
    """Test graceful handling of LLM failure in process endpoint."""
    with patch("main.openrouter_client.chat_completion") as mock_llm:
        # Simulate an exception from requests or openrouter
        mock_llm.side_effect = Exception("API connection failed")

        response = client.post(
            "/api/process",
            json={"text": "milk"}
        )

        assert response.status_code == 500
        assert "Error processing request" in response.json()["detail"]


def test_llm_invalid_json(client, temp_db):
    """Test handling of invalid JSON from LLM."""
    with patch("main.openrouter_client.chat_completion") as mock_llm:
        # Return invalid JSON
        mock_llm.return_value = ("Not JSON at all", {"input_tokens": 10, "output_tokens": 5, "cost": 0.0})

        response = client.post(
            "/api/process",
            json={"text": "milk"}
        )

        assert response.status_code == 500
        assert "Failed to parse LLM response" in response.json()["detail"]


def test_ocr_failure(client, temp_db):
    """Test handling of OCR failure (empty result)."""
    with patch("main.ocr_images_with_llm") as mock_ocr:
        # Mock OCR returning empty text
        mock_ocr.return_value = ("", {})

        response = client.post(
            "/api/process-image",
            json={"image": "data:image/png;base64,fake"}
        )

        assert response.status_code == 400
        assert "Could not extract any text" in response.json()["detail"]


def test_process_multiple_images(client, temp_db, mock_list_data):
    """Test that several images are OCR'd together into one list."""
    images = ["data:image/png;base64,first", "data:image/jpeg;base64,second"]
    with patch("main.ocr_images_with_llm") as mock_ocr, \
         patch("main.process_items_with_llm") as mock_process:
        mock_ocr.return_value = ("milk\nbread", {"cost": 0.0002})
        mock_process.return_value = (mock_list_data, {"cost": 0.0001})

        response = client.post(
            "/api/process-image",
            json={"images": images, "supermarket": "tesco"}
        )

        assert response.status_code == 200
        mock_ocr.assert_called_once_with(images)
        mock_process.assert_called_once_with("milk\nbread", "tesco")

        list_id = response.json()["list_id"]
        with database.get_db() as conn:
            row = conn.execute(
                "SELECT raw_input, input_type FROM shopping_lists WHERE id = ?",
                (list_id,)
            ).fetchone()
        assert row["raw_input"] == "milk\nbread"
        assert row["input_type"] == "image"


def test_process_image_requires_an_image(client, temp_db):
    """Test that a request with no images is rejected before any LLM call."""
    with patch("main.ocr_images_with_llm") as mock_ocr:
        for payload in ({}, {"images": []}, {"images": [""]}):
            response = client.post("/api/process-image", json=payload)
            assert response.status_code == 400
            assert response.json()["detail"] == "No image provided"
        mock_ocr.assert_not_called()


def test_process_image_rejects_too_many_images(client, temp_db):
    """Test that more than MAX_IMAGES images is rejected before any LLM call."""
    images = ["data:image/png;base64,x"] * (main.MAX_IMAGES + 1)
    with patch("main.ocr_images_with_llm") as mock_ocr:
        response = client.post("/api/process-image", json={"images": images})

        assert response.status_code == 400
        assert "Too many images" in response.json()["detail"]
        mock_ocr.assert_not_called()


def test_ocr_sends_every_image_in_one_request():
    """Test that each image becomes its own image part in a single vision request."""
    usage = {"model": "vision", "input_tokens": 1, "output_tokens": 1, "cost": 0.0}
    with patch.object(main.openrouter_client, "chat_completion") as mock_chat:
        mock_chat.return_value = ("milk", usage)

        text, returned_usage = main.ocr_images_with_llm(
            ["data:image/png;base64,AAA", "BBB"]
        )

        assert (text, returned_usage) == ("milk", usage)
        mock_chat.assert_called_once()
        assert mock_chat.call_args.kwargs["model"] == main.VISION_MODEL_NAME
        content = mock_chat.call_args.kwargs["messages"][0]["content"]
        assert content[0]["type"] == "text"
        assert "these 2 shopping list images" in content[0]["text"]
        assert [part["image_url"]["url"] for part in content[1:]] == [
            "data:image/png;base64,AAA",
            "data:image/png;base64,BBB",
        ]


def test_ocr_single_image_keeps_single_image_prompt():
    """Test that a lone image is still described as a single image."""
    usage = {"model": "vision", "input_tokens": 1, "output_tokens": 1, "cost": 0.0}
    with patch.object(main.openrouter_client, "chat_completion") as mock_chat:
        mock_chat.return_value = ("milk", usage)

        main.ocr_images_with_llm(["data:image/png;base64,AAA"])

        content = mock_chat.call_args.kwargs["messages"][0]["content"]
        assert content[0]["text"].startswith("Extract all text from this shopping list image.")
        assert len(content) == 2


def test_ocr_keeps_supported_image_types():
    """Test that JPEG/WebP keep their type; unknown types and raw base64 fall back to PNG."""
    usage = {"model": "vision", "input_tokens": 1, "output_tokens": 1, "cost": 0.0}
    with patch.object(main.openrouter_client, "chat_completion") as mock_chat:
        mock_chat.return_value = ("milk", usage)

        main.ocr_images_with_llm([
            "data:image/jpeg;base64,AAA",
            "data:image/webp;base64,BBB",
            "data:application/octet-stream;base64,CCC",
            "DDD",
        ])

        content = mock_chat.call_args.kwargs["messages"][0]["content"]
        assert [part["image_url"]["url"] for part in content[1:]] == [
            "data:image/jpeg;base64,AAA",
            "data:image/webp;base64,BBB",
            "data:image/png;base64,CCC",
            "data:image/png;base64,DDD",
        ]


# --- Versioning/Realtime Tests ---

def test_list_versioning(client, temp_db, mock_list_data):
    """Test that every update gets a unique monotonic revision."""
    list_id = database.create_shopping_list(mock_list_data, "tesco")

    response = client.get(f"/api/list/{list_id}/version")
    assert response.status_code == 200
    assert response.json()["revision"] == 0

    list_data = database.get_shopping_list(list_id)
    item_id = list_data['groups'][0]['items'][0]['id']

    # Two same-second updates must still produce distinct versions.
    assert database.update_item_status(list_id, item_id, True) == 1
    assert database.update_item_status(list_id, item_id, False) == 2

    response = client.get(f"/api/list/{list_id}/version")
    assert response.json()["revision"] == 2


def test_init_db_adds_revision_to_existing_database(temp_db):
    """Test migration of databases created before realtime revisions."""
    with sqlite3.connect(temp_db) as conn:
        conn.execute("DROP TABLE shopping_items")
        conn.execute("DROP TABLE shopping_lists")
        conn.execute('''
            CREATE TABLE shopping_lists (
                id TEXT PRIMARY KEY,
                supermarket TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.execute(
            "INSERT INTO shopping_lists (id, supermarket) VALUES ('abc12', 'tesco')"
        )

    database.init_db()

    with sqlite3.connect(temp_db) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(shopping_lists)")}
        revision = conn.execute(
            "SELECT revision FROM shopping_lists WHERE id = 'abc12'"
        ).fetchone()[0]

    assert "revision" in columns
    assert revision == 0


def test_list_event_broker_fans_out_and_collapses_backlog():
    """Test list-scoped event fan-out and slow-client catch-up behavior."""
    broker = ListEventBroker(queue_size=1)
    first = broker.subscribe("abc12")
    second = broker.subscribe("abc12")
    unrelated = broker.subscribe("other")

    broker.publish("abc12", {"type": "item.updated", "revision": 1})
    broker.publish("abc12", {"type": "item.updated", "revision": 2})

    assert first.get_nowait()["revision"] == 2
    assert second.get_nowait()["revision"] == 2
    assert unrelated.empty()

    broker.unsubscribe("abc12", first)
    broker.unsubscribe("abc12", second)
    assert "abc12" not in broker.subscribers


def test_sse_event_format():
    event = {"type": "item.updated", "revision": 3, "checked": True}
    message = format_sse_event(event)

    assert message.startswith("event: list-change\n")
    assert 'data: {"type":"item.updated","revision":3,"checked":true}\n\n' in message


def test_version_not_found(client, temp_db):
    """Test version endpoint for missing list."""
    response = client.get("/api/list/abcde/version")
    assert response.status_code == 404

    response = client.get("/api/list/abcde/events")
    assert response.status_code == 404


def test_multi_tab_live_updates_fanout(client, temp_db):
    """Simulate two tabs subscribed to real-time events checking off different items."""
    list_data_two_items = [
        {"name": "Milk", "quantity": "1 pint", "area": "dairy", "area_order": 1},
        {"name": "Bread", "quantity": "1 loaf", "area": "bakery", "area_order": 2},
    ]
    list_id = database.create_shopping_list(list_data_two_items, "tesco")
    list_data = database.get_shopping_list(list_id)

    # Get two items from the list to toggle from separate tabs
    item1_id = list_data['groups'][0]['items'][0]['id']
    item2_id = list_data['groups'][1]['items'][0]['id']

    # Subscribe Tab 1 and Tab 2 event listeners
    tab1_queue = main.list_event_broker.subscribe(list_id)
    tab2_queue = main.list_event_broker.subscribe(list_id)

    try:
        # Tab 1 checks item 1
        res1 = client.put(f"/api/list/{list_id}/item/{item1_id}", json={"checked": True})
        assert res1.status_code == 200
        rev1 = res1.json()["revision"]

        # Tab 2 checks item 2
        res2 = client.put(f"/api/list/{list_id}/item/{item2_id}", json={"checked": True})
        assert res2.status_code == 200
        rev2 = res2.json()["revision"]

        # Monotonic revision sequence: rev2 must be rev1 + 1
        assert rev1 == 1
        assert rev2 == 2

        # Both Tab 1 and Tab 2 queues must receive both update events in exact sequence
        event1_tab1 = tab1_queue.get_nowait()
        event2_tab1 = tab1_queue.get_nowait()

        event1_tab2 = tab2_queue.get_nowait()
        event2_tab2 = tab2_queue.get_nowait()

        assert event1_tab1 == {"type": "item.updated", "revision": 1, "item_id": item1_id, "checked": True}
        assert event2_tab1 == {"type": "item.updated", "revision": 2, "item_id": item2_id, "checked": True}

        assert event1_tab2 == event1_tab1
        assert event2_tab2 == event2_tab1

        # Verify DB state has both items checked
        updated_list = database.get_shopping_list(list_id)
        items_by_id = {i['id']: i['checked'] for g in updated_list['groups'] for i in g['items']}
        assert items_by_id[item1_id] is True
        assert items_by_id[item2_id] is True
    finally:
        main.list_event_broker.unsubscribe(list_id, tab1_queue)
        main.list_event_broker.unsubscribe(list_id, tab2_queue)


def test_sse_events_stream_endpoint(client, temp_db, mock_list_data):
    """Test connected event emission on list events endpoint."""
    list_id = database.create_shopping_list(mock_list_data, "tesco")

    # Connect to event stream
    with client.stream("GET", f"/api/list/{list_id}/events") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        # Read first SSE message chunk
        lines = []
        for line in response.iter_lines():
            if line:
                lines.append(line)
            if len(lines) >= 2:
                break

        assert lines[0] == "event: list-change"
        assert lines[1] == 'data: {"type":"connected","revision":0}'

