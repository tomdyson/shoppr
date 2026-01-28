
"""
Advanced tests for Shoppr application.
Covers PDF generation, error handling, and edge cases.
"""

import json
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

import database
import main
from main import app, strip_markdown_code_blocks


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
    with patch("main.litellm_client.chat_completion") as mock_llm:
        # Simulate an exception from requests or litellm
        mock_llm.side_effect = Exception("API connection failed")

        response = client.post(
            "/api/process",
            json={"text": "milk"}
        )

        assert response.status_code == 500
        assert "Error processing request" in response.json()["detail"]


def test_llm_invalid_json(client, temp_db):
    """Test handling of invalid JSON from LLM."""
    with patch("main.litellm_client.chat_completion") as mock_llm:
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
    with patch("main.ocr_image_with_llm") as mock_ocr:
        # Mock OCR returning empty text
        mock_ocr.return_value = ("", {})

        response = client.post(
            "/api/process-image",
            json={"image": "data:image/png;base64,fake"}
        )

        assert response.status_code == 400
        assert "Could not extract any text" in response.json()["detail"]


# --- Versioning/Polling Tests ---

def test_list_versioning(client, temp_db, mock_list_data):
    """Test that list version changes on update."""
    list_id = database.create_shopping_list(mock_list_data, "tesco")
    
    # Get initial version
    response = client.get(f"/api/list/{list_id}/version")
    assert response.status_code == 200
    v1 = response.json().get("updated_at")
    assert v1 is not None

    # Update item
    list_data = database.get_shopping_list(list_id)
    item_id = list_data['groups'][0]['items'][0]['id']
    
    # Wait a tiny bit to ensure timestamp difference if resolution is low? 
    # Usually sqlite current_timestamp is second resolution.
    import time
    time.sleep(1.1) 

    database.update_item_status(list_id, item_id, True)

    # Get v2
    response = client.get(f"/api/list/{list_id}/version")
    v2 = response.json().get("updated_at")

    assert v1 != v2


def test_version_not_found(client, temp_db):
    """Test version endpoint for missing list."""
    response = client.get("/api/list/abcde/version")
    assert response.status_code == 404
