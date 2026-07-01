from typing import Any
from abc import ABC, abstractmethod


class BaseHandler(ABC):
    path: str | None = None

    @classmethod
    @abstractmethod
    async def handle_request(
        cls, payload: dict[str, Any], dev_mode: bool = False
    ) -> dict[str, Any]:
        pass
