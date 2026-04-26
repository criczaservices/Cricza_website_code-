import sqlite3
import os

db_path = 'cricza_v11.db'

def inspect_schema():
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("--- User Table ---")
    cursor.execute("PRAGMA table_info(user)")
    for col in cursor.fetchall():
        print(col)

    print("\n--- Booking Table ---")
    cursor.execute("PRAGMA table_info(booking)")
    for col in cursor.fetchall():
        print(col)

    conn.close()

if __name__ == "__main__":
    inspect_schema()
