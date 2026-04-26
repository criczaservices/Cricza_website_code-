import sqlite3
import datetime

def migrate():
    sqlite_db = 'd:/cricza building/cricza_v11.db'
    conn = sqlite3.connect(sqlite_db)
    cursor = conn.cursor()

    # Get list of tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [t[0] for t in cursor.fetchall() if not t[0].startswith('sqlite_')]

    schema_sql = []
    data_sql = []

    # Table creation order to handle foreign keys
    # user, turf, coupon, booking, turf_off_date, withdrawal_request, rate_limit, idempotency_record
    ordered_tables = [
        'user', 'turf', 'coupon', 'booking', 'turf_off_date', 
        'withdrawal_request', 'rate_limit', 'idempotency_record'
    ]

    # Map SQLite types to PostgreSQL types
    type_map = {
        'INTEGER': 'SERIAL',
        'TEXT': 'TEXT',
        'VARCHAR': 'VARCHAR',
        'FLOAT': 'DOUBLE PRECISION',
        'BOOLEAN': 'BOOLEAN',
        'DATETIME': 'TIMESTAMP',
    }

    # Manual schema generation based on models.py for better accuracy
    schema_sql.append("""
-- PostgreSQL Schema for Cricza

CREATE TABLE IF NOT EXISTS "user" (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(120) UNIQUE NOT NULL,
    password_hash VARCHAR(200),
    google_id VARCHAR(100) UNIQUE,
    profile_pic VARCHAR(500),
    phone VARCHAR(20),
    role VARCHAR(20) NOT NULL DEFAULT 'Customer',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    subscription_plan VARCHAR(50),
    subscription_price DOUBLE PRECISION,
    subscription_start TIMESTAMP,
    subscription_end TIMESTAMP,
    wallet_balance DOUBLE PRECISION DEFAULT 0.0,
    razorpay_key_id VARCHAR(100),
    razorpay_key_secret VARCHAR(100),
    reset_otp VARCHAR(6),
    otp_expiry TIMESTAMP
);

CREATE TABLE IF NOT EXISTS "turf" (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER REFERENCES "user"(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    location VARCHAR(200) NOT NULL,
    pincode VARCHAR(10),
    price_per_hour DOUBLE PRECISION NOT NULL,
    photo_url VARCHAR(500),
    open_time INTEGER NOT NULL DEFAULT 6,
    close_time INTEGER NOT NULL DEFAULT 23,
    is_suspended BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS "coupon" (
    id SERIAL PRIMARY KEY,
    turf_id INTEGER REFERENCES "turf"(id) ON DELETE CASCADE NOT NULL,
    code VARCHAR(20) UNIQUE NOT NULL,
    discount_amount DOUBLE PRECISION NOT NULL,
    usage_limit INTEGER NOT NULL DEFAULT 10,
    used_count INTEGER NOT NULL DEFAULT 0,
    valid_until VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS "booking" (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES "user"(id) ON DELETE CASCADE NOT NULL,
    turf_id INTEGER REFERENCES "turf"(id) ON DELETE CASCADE NOT NULL,
    date VARCHAR(20) NOT NULL,
    time_slot VARCHAR(500) NOT NULL,
    cost DOUBLE PRECISION NOT NULL,
    razorpay_order_id VARCHAR(100),
    razorpay_payment_id VARCHAR(100),
    payment_status VARCHAR(20) DEFAULT 'Pending',
    payment_to VARCHAR(20),
    offline_customer_name VARCHAR(100),
    offline_customer_email VARCHAR(120),
    offline_customer_phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    coupon_code VARCHAR(20)
);

CREATE TABLE IF NOT EXISTS "turf_off_date" (
    id SERIAL PRIMARY KEY,
    turf_id INTEGER REFERENCES "turf"(id) ON DELETE CASCADE NOT NULL,
    off_date VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS "withdrawal_request" (
    id SERIAL PRIMARY KEY,
    owner_id INTEGER REFERENCES "user"(id) ON DELETE CASCADE NOT NULL,
    amount DOUBLE PRECISION NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'Pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    paid_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS "rate_limit" (
    id SERIAL PRIMARY KEY,
    key VARCHAR(255),
    hits INTEGER DEFAULT 0,
    last_hit TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    period_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rate_limit_key ON "rate_limit"(key);

CREATE TABLE IF NOT EXISTS "idempotency_record" (
    id SERIAL PRIMARY KEY,
    idempotency_key VARCHAR(255) UNIQUE NOT NULL,
    user_id INTEGER,
    endpoint VARCHAR(255),
    response_body TEXT,
    status_code INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_idempotency_key ON "idempotency_record"(idempotency_key);
""")

    # Data extraction
    for table in ordered_tables:
        cursor.execute(f"SELECT * FROM \"{table}\"")
        rows = cursor.fetchall()
        if not rows:
            continue
            
        columns = [description[0] for description in cursor.description]
        col_names = ", ".join([f'"{c}"' for c in columns])
        
        for row in rows:
            values = []
            for val in row:
                if val is None:
                    values.append("NULL")
                elif isinstance(val, str):
                    # Escape single quotes for SQL
                    val_esc = val.replace("'", "''")
                    values.append(f"'{val_esc}'")
                elif isinstance(val, bool):
                    values.append("TRUE" if val else "FALSE")
                else:
                    values.append(str(val))
            
            val_str = ", ".join(values)
            data_sql.append(f"INSERT INTO \"{table}\" ({col_names}) VALUES ({val_str});")

    # Fix sequences for SERIAL columns after data insertion
    for table in ordered_tables:
        data_sql.append(f"SELECT setval(pg_get_serial_sequence('\"{table}\"', 'id'), COALESCE(MAX(id), 1)) FROM \"{table}\";")

    with open('d:/cricza building/neon_migration.sql', 'w', encoding='utf-8') as f:
        f.write("\n".join(schema_sql))
        f.write("\n\n-- DATA INSERTION --\n\n")
        f.write("\n".join(data_sql))

    conn.close()
    print("Migration script generated: neon_migration.sql")

if __name__ == "__main__":
    migrate()
