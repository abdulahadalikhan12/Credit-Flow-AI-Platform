from shared.database import init_db_engine

# Initialize engine and SessionLocal specifically for 'ai_db'
engine, SessionLocal = init_db_engine("ai_db")
