from typing import Any
from .BaseHandler import BaseHandler


class EchoHandler(BaseHandler):
    """
    Simply echoes the given payload back to the callback.
    Can be used to test if the worker is available and responds.
    """

    path: str = "echo"

    @classmethod
    async def handle_request(
        cls, payload: dict[str, Any], dev_mode: bool = False
    ) -> dict[str, Any]:
        return payload
