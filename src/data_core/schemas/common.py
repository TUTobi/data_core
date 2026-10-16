from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator

from data_core.timeutil import as_utc

# Datetime that is always aware UTC (naive input is interpreted as UTC).
UtcDatetime = Annotated[datetime, AfterValidator(as_utc)]
