from app import app, db, Turf

def test_query():
    with app.app_context():
        try:
            turfs = Turf.query.filter_by(is_suspended=False).all()
            for t in turfs:
                print(f"--- {t.name} ---")
                print(f"Description: {t.description}")
        except Exception as e:
            print(f"Query failed: {e}")

if __name__ == "__main__":
    test_query()
