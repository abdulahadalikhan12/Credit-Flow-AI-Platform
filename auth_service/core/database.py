from shared.database import init_db_engine

# Initialize engine and SessionLocal specifically for 'auth_db'
engine, SessionLocal = init_db_engine("auth_db")
