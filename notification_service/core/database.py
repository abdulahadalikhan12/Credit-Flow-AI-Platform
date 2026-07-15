from shared.database import init_db_engine

# Initialize engine and SessionLocal specifically for 'notification_db'
engine, SessionLocal = init_db_engine("notification_db")
