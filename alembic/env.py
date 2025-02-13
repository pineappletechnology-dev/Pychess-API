from logging.config import fileConfig

from alembic import context
from database.database import Base, engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None

def run_migrations():
    Base.metadata.create_all(bind=engine)

run_migrations()
