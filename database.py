import os
import secrets
import sqlite3
import string
from contextlib import contextmanager
from typing import List, Optional

# Characters for generating short slugs (alphanumeric, no ambiguous chars)
SLUG_CHARS = string.ascii_lowercase + string.digits
SLUG_LENGTH = 5


def generate_slug() -> str:
    """Generate a random 5-character alphanumeric slug."""
    return ''.join(secrets.choice(SLUG_CHARS) for _ in range(SLUG_LENGTH))

# Get database path from environment variable, default to local directory
DB_PATH = os.getenv('DB_PATH', 'shopping.db')

# Ensure the directory exists
if os.path.dirname(DB_PATH):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS shopping_lists (
            id TEXT PRIMARY KEY,
            supermarket TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

        # Add updated_at column if it doesn't exist (migration for existing DBs)
        try:
            conn.execute('ALTER TABLE shopping_lists ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
        except sqlite3.OperationalError:
            pass  # Column already exists

        conn.execute('''
        CREATE TABLE IF NOT EXISTS shopping_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            list_id TEXT NOT NULL,
            name TEXT NOT NULL,
            area TEXT NOT NULL,
            area_order INTEGER NOT NULL,
            item_order INTEGER NOT NULL,
            quantity TEXT,
            checked BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (list_id) REFERENCES shopping_lists (id)
        )
        ''')

        conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_items_list_id
        ON shopping_items(list_id)
        ''')

        conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_items_order
        ON shopping_items(area_order, item_order)
        ''')

        conn.commit()


def create_shopping_list(items: List[dict], supermarket: Optional[str] = None) -> str:
    """Create a new shopping list with items."""
    list_id = generate_slug()

    with get_db() as conn:
        conn.execute(
            'INSERT INTO shopping_lists (id, supermarket) VALUES (?, ?)',
            (list_id, supermarket)
        )

        for i, item in enumerate(items):
            conn.execute('''
            INSERT INTO shopping_items
            (list_id, name, area, area_order, item_order, quantity, checked)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                list_id,
                item['name'],
                item['area'],
                item['area_order'],
                i,
                item.get('quantity'),
                False
            ))

        conn.commit()

    return list_id


def get_shopping_list(list_id: str) -> Optional[dict]:
    """Get a shopping list with all items grouped by area."""
    with get_db() as conn:
        # Check if list exists and get supermarket
        list_row = conn.execute(
            'SELECT id, supermarket, updated_at FROM shopping_lists WHERE id = ?',
            (list_id,)
        ).fetchone()

        if not list_row:
            return None

        # Get all items ordered by area_order then item_order
        items = conn.execute('''
        SELECT id, name, area, area_order, quantity, checked
        FROM shopping_items
        WHERE list_id = ?
        ORDER BY area_order, item_order
        ''', (list_id,)).fetchall()

        # Group items by area
        groups = {}
        for item in items:
            area = item['area']
            if area not in groups:
                groups[area] = {
                    'area': area,
                    'area_order': item['area_order'],
                    'items': []
                }
            groups[area]['items'].append({
                'id': item['id'],
                'name': item['name'],
                'quantity': item['quantity'],
                'checked': bool(item['checked'])
            })

        # Sort groups by area_order and convert to list
        sorted_groups = sorted(groups.values(), key=lambda g: g['area_order'])

        return {
            'list_id': list_row['id'],
            'supermarket': list_row['supermarket'],
            'updated_at': list_row['updated_at'],
            'groups': sorted_groups
        }


def update_item_status(list_id: str, item_id: int, checked: bool) -> bool:
    """Update the checked status of a single item."""
    with get_db() as conn:
        # Verify the item belongs to the list
        item = conn.execute('''
        SELECT id FROM shopping_items
        WHERE id = ? AND list_id = ?
        ''', (item_id, list_id)).fetchone()

        if not item:
            return False

        conn.execute(
            'UPDATE shopping_items SET checked = ? WHERE id = ?',
            (checked, item_id)
        )
        # Update the list's updated_at timestamp
        conn.execute(
            'UPDATE shopping_lists SET updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (list_id,)
        )
        conn.commit()
        return True


def get_list_progress(list_id: str) -> Optional[dict]:
    """Get the progress (checked/total) for a list."""
    with get_db() as conn:
        result = conn.execute('''
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN checked THEN 1 ELSE 0 END) as checked
        FROM shopping_items
        WHERE list_id = ?
        ''', (list_id,)).fetchone()

        if result['total'] == 0:
            return None

        return {
            'total': result['total'],
            'checked': result['checked'] or 0
        }


def get_list_version(list_id: str) -> Optional[str]:
    """Get just the updated_at timestamp for polling."""
    with get_db() as conn:
        result = conn.execute(
            'SELECT updated_at FROM shopping_lists WHERE id = ?',
            (list_id,)
        ).fetchone()

        if not result:
            return None
        return result['updated_at']


def update_shopping_list(list_id: str, new_items: List[dict], changes: dict) -> bool:
    """
    Update a shopping list with new items while preserving checked status.

    Args:
        list_id: The list ID to update
        new_items: List of new items from LLM with name, quantity, area, area_order
        changes: Dict with 'kept', 'added', 'removed' item names for tracking

    Returns:
        True if successful, False otherwise
    """
    with get_db() as conn:
        # Verify list exists
        list_row = conn.execute(
            'SELECT id FROM shopping_lists WHERE id = ?',
            (list_id,)
        ).fetchone()

        if not list_row:
            return False

        # Get existing items with their checked status
        existing_items = conn.execute('''
        SELECT name, checked FROM shopping_items WHERE list_id = ?
        ''', (list_id,)).fetchall()

        # Create a map of item names to checked status (case-insensitive)
        checked_status = {item['name'].lower(): bool(item['checked']) for item in existing_items}

        # Delete all existing items
        conn.execute('DELETE FROM shopping_items WHERE list_id = ?', (list_id,))

        # Insert new items, preserving checked status where names match
        for i, item in enumerate(new_items):
            item_name_lower = item['name'].lower()
            # Preserve checked status if item existed before
            was_checked = checked_status.get(item_name_lower, False)

            conn.execute('''
            INSERT INTO shopping_items
            (list_id, name, area, area_order, item_order, quantity, checked)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                list_id,
                item['name'],
                item['area'],
                item['area_order'],
                i,
                item.get('quantity'),
                was_checked
            ))

        # Update the updated_at timestamp
        conn.execute(
            'UPDATE shopping_lists SET updated_at = CURRENT_TIMESTAMP WHERE id = ?',
            (list_id,)
        )

        conn.commit()
        return True
