#!/usr/bin/env python3
"""Management command to delete shopping lists older than 28 days."""
import os
import sqlite3
from datetime import datetime, timedelta

# Get database path from environment variable, default to local directory
DB_PATH = os.getenv('DB_PATH', 'shopping.db')


def cleanup_old_lists(days: int = 28) -> int:
    """Delete shopping lists older than the specified number of days.

    Returns the number of lists deleted.
    """
    cutoff = datetime.now() - timedelta(days=days)
    cutoff_str = cutoff.strftime('%Y-%m-%d %H:%M:%S')

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()

        # Get count of lists to delete
        cursor.execute(
            'SELECT COUNT(*) FROM shopping_lists WHERE created_at < ?',
            (cutoff_str,)
        )
        count = cursor.fetchone()[0]

        if count > 0:
            # Delete items first (foreign key constraint)
            cursor.execute('''
                DELETE FROM shopping_items
                WHERE list_id IN (
                    SELECT id FROM shopping_lists WHERE created_at < ?
                )
            ''', (cutoff_str,))

            # Delete the lists
            cursor.execute(
                'DELETE FROM shopping_lists WHERE created_at < ?',
                (cutoff_str,)
            )

            conn.commit()

        return count
    finally:
        conn.close()


if __name__ == '__main__':
    deleted = cleanup_old_lists()
    print(f"Deleted {deleted} shopping list(s) older than 28 days")
