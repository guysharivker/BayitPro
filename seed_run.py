from app.db import SessionLocal
from app.services.seed_service import seed_data

def run():
    db = SessionLocal()
    try:
        result = seed_data(db)
        print("Seed completed:", result)
    finally:
        db.close()

if __name__ == "__main__":
    run()
