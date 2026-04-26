import sqlite3
import os

db_path = 'cricza_v11.db'

def fix_database():
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. Create the new booking table with correct schema (no order_id)
        print("Creating new booking table schema...")
        cursor.execute("""
            CREATE TABLE booking_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL,
                turf_id INTEGER NOT NULL,
                date VARCHAR(20) NOT NULL,
                time_slot VARCHAR(500) NOT NULL,
                cost FLOAT NOT NULL,
                razorpay_order_id VARCHAR(100),
                razorpay_payment_id VARCHAR(100),
                payment_status VARCHAR(20) DEFAULT 'Pending',
                payment_to VARCHAR(20),
                offline_customer_name VARCHAR(100),
                offline_customer_email VARCHAR(120),
                created_at DATETIME
            )
        """)

        # 2. Copy data from old table to new table
        # We map columns explicitly, skipping the old 'order_id'
        print("Migrating data from old table...")
        cursor.execute("""
            INSERT INTO booking_new (
                id, customer_id, turf_id, date, time_slot, cost, 
                razorpay_order_id, razorpay_payment_id, payment_status, 
                payment_to, offline_customer_name, offline_customer_email, created_at
            )
            SELECT 
                id, customer_id, turf_id, date, time_slot, cost, 
                razorpay_order_id, razorpay_payment_id, payment_status, 
                payment_to, offline_customer_name, offline_customer_email, created_at
            FROM booking
        """)

        # 3. Swap the tables
        print("Swapping tables...")
        cursor.execute("DROP TABLE booking")
        cursor.execute("ALTER TABLE booking_new RENAME TO booking")

        conn.commit()
        print("Database migration successful! Problematic 'order_id' column removed.")

    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {str(e)}")
    finally:
        conn.close()

if __name__ == "__main__":
    fix_database()
