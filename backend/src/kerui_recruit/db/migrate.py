from sqlalchemy import Engine

from kerui_recruit.db.base import Base
from kerui_recruit.db import models as _models


def migrate(engine: Engine) -> None:
    Base.metadata.create_all(engine)
