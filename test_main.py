"""
Tests for Shoppr shopping list application.

Run with: pytest test_main.py -v
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
from main import app


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    temp_fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_fd)

    # Set the database path
    original_db_path = database.DB_PATH
    database.DB_PATH = temp_path

    # Initialize the database
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
def mock_llm_response():
    """Mock LLM response data for testing."""
    return [
        {
            "name": "Semi-skimmed milk",
            "quantity": "2L",
            "area": "dairy",
            "area_order": 3
        },
        {
            "name": "Bananas",
            "quantity": "6",
            "area": "produce",
            "area_order": 1
        },
        {
            "name": "Bread",
            "quantity": None,
            "area": "bakery",
            "area_order": 2
        }
    ]


@pytest.fixture
def mock_llm_usage():
    """Mock LLM usage stats."""
    return {
        "model": "gemini-2.5-flash-lite",
        "input_tokens": 150,
        "output_tokens": 75,
        "cost": 0.000123
    }


# Test 1: Database - Create and retrieve shopping list
def test_database_create_and_get_list(temp_db, mock_llm_response):
    """Test creating a shopping list and retrieving it from database."""
    # Create a list
    list_id = database.create_shopping_list(mock_llm_response, "tesco")

    # Verify list ID format (5-char alphanumeric)
    assert len(list_id) == 5
    assert list_id.isalnum()
    assert list_id.islower()

    # Retrieve the list
    list_data = database.get_shopping_list(list_id)

    assert list_data is not None
    assert list_data['list_id'] == list_id
    assert list_data['supermarket'] == 'tesco'
    assert len(list_data['groups']) == 3  # 3 different areas

    # Verify items are grouped correctly
    areas = {group['area'] for group in list_data['groups']}
    assert areas == {'dairy', 'produce', 'bakery'}

    # Verify items are ordered by area_order
    area_orders = [group['area_order'] for group in list_data['groups']]
    assert area_orders == sorted(area_orders)  # Should be [1, 2, 3]


# Test 2: Database - Update item status
def test_database_update_item_status(temp_db, mock_llm_response):
    """Test updating checked status of items."""
    # Create a list
    list_id = database.create_shopping_list(mock_llm_response, "tesco")
    list_data = database.get_shopping_list(list_id)

    # Get first item
    first_item = list_data['groups'][0]['items'][0]
    item_id = first_item['id']

    # Initially unchecked
    assert first_item['checked'] is False

    # Update to checked
    success = database.update_item_status(list_id, item_id, True)
    assert success is True

    # Verify update
    updated_list = database.get_shopping_list(list_id)
    updated_item = next(
        item for group in updated_list['groups']
        for item in group['items']
        if item['id'] == item_id
    )
    assert updated_item['checked'] is True

    # Test updating non-existent item
    success = database.update_item_status(list_id, 99999, True)
    assert success is False


# Test 3: Database - Update shopping list with edit
def test_database_update_shopping_list(temp_db, mock_llm_response):
    """Test updating a shopping list with new items."""
    # Create initial list
    list_id = database.create_shopping_list(mock_llm_response, "tesco")

    # Find and check the bananas item specifically
    list_data = database.get_shopping_list(list_id)
    bananas_item = next(
        item for group in list_data['groups']
        for item in group['items']
        if 'banana' in item['name'].lower()
    )
    database.update_item_status(list_id, bananas_item['id'], True)

    # New items (remove bread, add eggs, keep milk and bananas)
    new_items = [
        {
            "name": "Semi-skimmed milk",
            "quantity": "2L",
            "area": "dairy",
            "area_order": 3
        },
        {
            "name": "Bananas",
            "quantity": "6",
            "area": "produce",
            "area_order": 1
        },
        {
            "name": "Free-range eggs",
            "quantity": "12",
            "area": "dairy",
            "area_order": 3
        }
    ]

    changes = {
        "kept": ["Semi-skimmed milk", "Bananas"],
        "added": ["Free-range eggs"],
        "removed": ["Bread"]
    }

    # Update list
    success = database.update_shopping_list(list_id, new_items, changes)
    assert success is True

    # Verify update
    updated_list = database.get_shopping_list(list_id)
    all_items = [
        item for group in updated_list['groups']
        for item in group['items']
    ]

    # Should have 3 items now
    assert len(all_items) == 3

    # Bananas should still be checked (preserved status)
    bananas_item = next(item for item in all_items if 'banana' in item['name'].lower())
    assert bananas_item['checked'] is True

    # New eggs should be unchecked
    eggs_item = next(item for item in all_items if 'eggs' in item['name'].lower())
    assert eggs_item['checked'] is False


# Test 4: API - Process text endpoint
def test_api_process_text(client, temp_db, mock_llm_response, mock_llm_usage):
    """Test the /api/process endpoint for text input."""
    with patch('main.process_items_with_llm') as mock_process:
        mock_process.return_value = (mock_llm_response, mock_llm_usage)

        response = client.post(
            "/api/process",
            json={
                "text": "milk\nbread\nbananas",
                "supermarket": "tesco"
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response structure
        assert 'list_id' in data
        assert len(data['list_id']) == 5
        assert data['supermarket'] == 'tesco'
        assert data['supermarket_display'] == 'Tesco'
        assert 'groups' in data
        assert len(data['groups']) == 3

        # Verify metadata includes usage stats
        assert 'meta' in data
        assert 'planning' in data['meta']
        assert data['meta']['planning']['cost'] == 0.000123

        # Verify LLM was called correctly
        mock_process.assert_called_once_with("milk\nbread\nbananas", "tesco")


# Test 5: API - Process image endpoint
def test_api_process_image(client, temp_db, mock_llm_response, mock_llm_usage):
    """Test the /api/process-image endpoint for OCR + categorization."""
    mock_ocr_usage = {
        "model": "gemini-2.5-flash",
        "input_tokens": 1200,
        "output_tokens": 50,
        "cost": 0.000456
    }

    with patch('main.ocr_image_with_llm') as mock_ocr, \
         patch('main.process_items_with_llm') as mock_process:

        mock_ocr.return_value = ("milk\nbread\nbananas", mock_ocr_usage)
        mock_process.return_value = (mock_llm_response, mock_llm_usage)

        # Fake base64 image
        fake_image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

        response = client.post(
            "/api/process-image",
            json={
                "image": fake_image,
                "supermarket": "tesco"
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Verify response includes both OCR and planning metadata
        assert 'meta' in data
        assert 'ocr' in data['meta']
        assert 'planning' in data['meta']
        assert data['meta']['ocr']['cost'] == 0.000456
        assert data['meta']['planning']['cost'] == 0.000123

        # Verify OCR was called with image
        mock_ocr.assert_called_once()


# Test 6: API - Edit list endpoint
def test_api_edit_list(client, temp_db, mock_llm_response, mock_llm_usage):
    """Test the /api/list/{list_id}/edit endpoint for natural language editing."""
    # First create a list
    list_id = database.create_shopping_list(mock_llm_response, "tesco")

    # Mock edited items (added salmon, removed bread)
    edited_items = [
        {
            "name": "Semi-skimmed milk",
            "quantity": "2L",
            "area": "dairy",
            "area_order": 3
        },
        {
            "name": "Bananas",
            "quantity": "6",
            "area": "produce",
            "area_order": 1
        },
        {
            "name": "Salmon fillets",
            "quantity": "400g",
            "area": "meat",
            "area_order": 4
        }
    ]

    changes = {
        "kept": ["Semi-skimmed milk", "Bananas"],
        "added": ["Salmon fillets"],
        "removed": ["Bread"]
    }

    with patch('main.process_edit_with_llm') as mock_edit:
        mock_edit.return_value = (edited_items, changes, mock_llm_usage)

        response = client.post(
            f"/api/list/{list_id}/edit",
            json={
                "text": "remove bread, add salmon fillets 400g"
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Verify changes are included in response
        assert 'changes' in data
        assert data['changes']['added'] == ["Salmon fillets"]
        assert data['changes']['removed'] == ["Bread"]
        assert data['changes']['kept'] == ["Semi-skimmed milk", "Bananas"]

        # Verify metadata
        assert 'meta' in data
        assert 'edit' in data['meta']


# Test 7: API - Get list endpoint
def test_api_get_list(client, temp_db, mock_llm_response):
    """Test the /api/list/{list_id} endpoint."""
    # Create a list
    list_id = database.create_shopping_list(mock_llm_response, "sainsburys")

    # Get the list via API
    response = client.get(f"/api/list/{list_id}")

    assert response.status_code == 200
    data = response.json()

    assert data['list_id'] == list_id
    assert data['supermarket'] == 'sainsburys'
    assert data['supermarket_display'] == "Sainsbury's"
    assert len(data['groups']) == 3

    # Test non-existent list
    response = client.get("/api/list/zzzzz")
    assert response.status_code == 404


# Test 8: API - Update item status endpoint
def test_api_update_item(client, temp_db, mock_llm_response):
    """Test the /api/list/{list_id}/item/{item_id} endpoint."""
    # Create a list
    list_id = database.create_shopping_list(mock_llm_response, "tesco")
    list_data = database.get_shopping_list(list_id)
    item_id = list_data['groups'][0]['items'][0]['id']

    # Check the item
    response = client.put(
        f"/api/list/{list_id}/item/{item_id}",
        json={"checked": True}
    )

    assert response.status_code == 200
    assert response.json()['success'] is True

    # Verify it was updated
    list_data = database.get_shopping_list(list_id)
    updated_item = next(
        item for group in list_data['groups']
        for item in group['items']
        if item['id'] == item_id
    )
    assert updated_item['checked'] is True

    # Test invalid item
    response = client.put(
        f"/api/list/{list_id}/item/99999",
        json={"checked": True}
    )
    assert response.status_code == 404


# Test 9: Slug validation
def test_slug_validation():
    """Test the is_valid_slug function."""
    # Valid slugs
    assert main.is_valid_slug("abc12") is True
    assert main.is_valid_slug("zzz99") is True
    assert main.is_valid_slug("00000") is True

    # Invalid slugs
    assert main.is_valid_slug("ABC12") is False  # uppercase
    assert main.is_valid_slug("abc-2") is False  # hyphen
    assert main.is_valid_slug("abc_2") is False  # underscore
    assert main.is_valid_slug("abcd") is False   # too short
    assert main.is_valid_slug("abcdef") is False # too long
    assert main.is_valid_slug("") is False       # empty


# Test 10: Error handling - Invalid supermarket
def test_api_invalid_supermarket(client, temp_db, mock_llm_response, mock_llm_usage):
    """Test that invalid supermarket values are rejected."""
    with patch('main.process_items_with_llm') as mock_process:
        mock_process.return_value = (mock_llm_response, mock_llm_usage)

        response = client.post(
            "/api/process",
            json={
                "text": "milk\nbread",
                "supermarket": "invalid_store"
            }
        )

        assert response.status_code == 400
        assert "Invalid supermarket" in response.json()['detail']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
