from app import app, db
from sqlalchemy import text

def fix_sequences():
    with app.app_context():
        # List of tables to fix
        tables = ['user', 'turf', 'booking', 'withdrawal_request', 'coupon', 'rate_limit', 'idempotency_record', 'turf_off_date']
        
        for table in tables:
            try:
                # Find the max ID
                result = db.session.execute(text(f'SELECT MAX(id) FROM "{table}"')).scalar()
                if result is not None:
                    # Reset the sequence
                    seq_name = f"{table}_id_seq"
                    db.session.execute(text(f"SELECT setval('{seq_name}', {result})"))
                    print(f"Fixed sequence for {table} to {result}")
                else:
                    print(f"No data in {table}, skipping sequence fix.")
            except Exception as e:
                print(f"Error fixing sequence for {table}: {e}")
        
        db.session.commit()
        print("All sequences fixed.")

if __name__ == "__main__":
    fix_sequences()
