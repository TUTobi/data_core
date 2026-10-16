from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    # All timestamps are stored timezone-aware (UTC).
    type_annotation_map = {datetime: DateTime(timezone=True)}
