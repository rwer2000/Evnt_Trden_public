from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

SCHEMA = "congress"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)
