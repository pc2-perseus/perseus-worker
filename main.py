"""
PERSEUS worker template

Please check out the README.md to learn about adding handlers.
"""

from os import getenv
from multiprocessing import Process, Queue
import inspect
import json
import requests
import logging
import asyncio
import jwt
from typing import Any

from fastapi import FastAPI, APIRouter, Request, Response, status, BackgroundTasks

import handlers

app = FastAPI()

router = APIRouter()
logger = logging.getLogger("uvicorn.info")

DEV_MODE: bool = getenv("DEV_MODE", "False").lower() in [
    "true",
    "1",
]


def load_whitelist(file_path="whitelist.txt"):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            whitelist = [line.strip() for line in f if line.strip()]
        return whitelist
    except FileNotFoundError:
        return []


def verify_job(token: str, job_id: str) -> bool:
    if DEV_MODE:
        return True
    for core_url in load_whitelist():
        try:
            pubkey_response = requests.get(
                (core_url[:-1] if core_url[-1] == "/" else core_url) + "/public-key",
                timeout=10,
            )
            if pubkey_response.status_code == 200:
                pubkey_response_json = pubkey_response.json()
                if "public_key" in pubkey_response_json:
                    pubkey = pubkey_response_json["public_key"]
                    decoded_token = jwt.decode(token, pubkey, algorithms=["RS256"])
                    if "user" in decoded_token and decoded_token["user"] == job_id:
                        return True
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.RequestException,
            requests.exceptions.Timeout,
        ):
            logger.error("Cannot access PERSEUS core instance on %s", core_url)
        except jwt.exceptions.InvalidSignatureError:
            continue
        except Exception as e:
            logger.error(e, exc_info=True)
    return False


def run_async_in_process(full_path: str, payload: dict[str, Any], q: Queue):
    inspect.getmembers(handlers, inspect.isclass)
    found = False
    for item in inspect.getmembers(handlers, inspect.isclass):
        if (
            issubclass(item[1], handlers.BaseHandler)
            and not item[0] == handlers.BaseHandler.__name__
            and hasattr(item[1], "path")
            and item[1].path == full_path
        ):
            found = True
            result = asyncio.run(item[1].handle_request(payload, DEV_MODE))
            q.put(result)
    if not found:
        q.put(None)


def run_task(
    full_path: str,
    payload: dict[str, Any],
    job_id: str,
    token: str,
    timeout: int,
    callback_url: str,
):
    try:
        q = Queue()
        p = Process(target=run_async_in_process, args=(full_path, payload, q))
        p.start()
        handler = q.get()
        p.join(timeout)

        if p.is_alive():
            p.terminate()
            p.join()
            logger.error("Timeout exceeded for job %s", job_id, exc_info=True)
            handler = {"error": "An error occurred. Please check the worker's log."}

    except Exception as e:
        logger.error(e, exc_info=True)
        handler = {"error": "An error occurred. Please check the worker's log."}

    if handler is None:
        logger.error("Could not find any handler for path %s", full_path)
        return

    try:
        handler["job_id"] = job_id
        if DEV_MODE:
            logger.info(
                "[DEV] Send callback to %s:\nToken: %s\nPayload: %s",
                callback_url,
                token,
                handler,
            )
        else:
            callback = requests.post(
                callback_url,
                headers={"Perseus-Token": token},
                json=handler,
                timeout=30,
            )
            if callback.status_code != 200:
                logger.error("Received status code %i", callback.status_code)
    except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
        logger.error(e, exc_info=True)


@router.post("/{full_path:path}")
async def process_post(
    full_path: str,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
):
    try:
        body = await request.json()
    except json.decoder.JSONDecodeError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return "No valid JSON"

    try:
        if DEV_MODE:
            callback_url = "<EXAMPLE_CALLBACK_URL>"
        else:
            callback_url = body["callback_url"]
    except KeyError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return "Missing field 'callback_url'"

    try:
        payload = body["payload"]
    except KeyError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return "Missing field 'payload'"

    if type(payload) is not dict:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return "Field 'payload' has to be a dictionary"

    try:
        if DEV_MODE:
            job_id = "<EXAMPLE_JOB_ID>"
        else:
            job_id = body["job_id"]
    except KeyError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return "Missing field 'job_id'"

    try:
        if DEV_MODE:
            token = "<EXAMPLE_TOKEN>"
        else:
            token = body["token"]
    except KeyError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return "Missing field 'token'"

    try:
        timeout = body["timeout"]
    except KeyError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return "Missing field 'timeout'"

    if DEV_MODE:
        logger.info(
            "[DEV] Received request with path %s and payload %s", full_path, payload
        )

    if not verify_job(token, job_id):
        response.status_code = status.HTTP_403_FORBIDDEN
        return "You are not allowed to submit jobs to this worker"

    background_tasks.add_task(
        run_task,
        full_path,
        payload,
        job_id,
        token,
        timeout,
        callback_url,
    )

    return True


app.include_router(router)
