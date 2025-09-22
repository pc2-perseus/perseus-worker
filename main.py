"""
PERSEUS worker template

To add your custom logic, go to handlers/handle_request.py.
"""

from multiprocessing import Process, Queue
import json
import requests
import logging
import asyncio
from typing import Any

from fastapi import FastAPI, APIRouter, Request, Response, status, BackgroundTasks

from handlers import handle_request

app = FastAPI()

router = APIRouter()


def run_async_in_process(full_path: str, payload: dict[str, Any], q: Queue):
    result = asyncio.run(handle_request(full_path, payload))
    q.put(result)


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
        p.join(timeout)

        if p.is_alive():
            p.terminate()
            p.join()
            logging.error("Timeout exceeded for job %s", job_id, exc_info=True)
            handler = {"error": "An error occurred. Please check the worker's log."}
        else:
            handler = q.get()
    except Exception as e:
        logging.error(e, exc_info=True)
        handler = {"error": "An error occurred. Please check the worker's log."}

    try:
        handler["job_id"] = job_id
        callback = requests.post(
            callback_url,
            headers={"Perseus-Token": token},
            json=handler,
            timeout=30,
        )
        if callback.status_code != 200:
            logging.error("Received status code %i", callback.status_code)
    except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
        logging.error(e, exc_info=True)


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
        job_id = body["job_id"]
    except KeyError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return "Missing field 'job_id'"

    try:
        token = body["token"]
    except KeyError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return "Missing field 'token'"

    try:
        timeout = body["timeout"]
    except KeyError:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return "Missing field 'timeout'"

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
