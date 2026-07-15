from shared.database import init_db_engine

# Initialize engine and SessionLocal specifically for 'credits_db'
engine, SessionLocal = init_db_engine("credits_db")
