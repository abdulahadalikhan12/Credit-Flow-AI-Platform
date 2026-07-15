from shared.database import init_db_engine

# Initialize engine and SessionLocal specifically for 'scheduler_db'
engine, SessionLocal = init_db_engine("scheduler_db")
