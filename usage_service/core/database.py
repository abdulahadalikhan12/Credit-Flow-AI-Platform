from shared.database import init_db_engine

# Initialize engine and SessionLocal specifically for 'usage_db'
engine, SessionLocal = init_db_engine("usage_db")
