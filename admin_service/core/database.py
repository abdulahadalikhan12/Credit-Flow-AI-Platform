from shared.database import init_db_engine

# Initialize engine and SessionLocal specifically for 'admin_db'
engine, SessionLocal = init_db_engine("admin_db")
