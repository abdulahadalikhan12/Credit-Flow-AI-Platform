from shared.database import init_db_engine

# Initialize engine and SessionLocal specifically for 'content_db'
engine, SessionLocal = init_db_engine("content_db")
