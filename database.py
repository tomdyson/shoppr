import os
import sqlite3
import uuid
from contextlib import contextmanager
from typing import List, Optional

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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

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
    list_id = str(uuid.uuid4())

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
            'SELECT id, supermarket FROM shopping_lists WHERE id = ?',
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
