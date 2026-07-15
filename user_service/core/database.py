from shared.database import init_db_engine

# Initialize engine and SessionLocal specifically for 'user_db'
engine, SessionLocal = init_db_engine("user_db")
