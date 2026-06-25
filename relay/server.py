"""
RFC Relay Server — runs on GCP port 8502.
Bridges RFC requests from Streamlit to the relay client running on the user's VPN laptop.
"""
import threading
import time
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="SAP RFC Relay Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_lock = threading.Lock()
_pending: dict = {}   # request_id -> request dict
_results: dict = {}   # request_id -> result dict
_last_poll: float = 0.0

RELAY_TIMEOUT = 10  # seconds before we consider relay disconnected


@app.get("/relay/status")
def status():
    with _lock:
        connected = (time.time() - _last_poll) < RELAY_TIMEOUT
        pending = len(_pending)
    return {"relay_connected": connected, "pending_requests": pending}


@app.post("/relay/request")
def submit_request(body: dict):
    request_id = str(uuid.uuid4())
    with _lock:
        _pending[request_id] = {"request": body, "submitted_at": time.time()}
    return {"request_id": request_id}


@app.get("/relay/poll")
def poll():
    """Relay client calls this every 2s to pick up pending requests."""
    global _last_poll
    with _lock:
        _last_poll = time.time()
        items = [
            {"request_id": rid, "request": data["request"]}
            for rid, data in list(_pending.items())
        ]
    return {"requests": items}


@app.post("/relay/result/{request_id}")
def post_result(request_id: str, body: dict):
    with _lock:
        _results[request_id] = body
        _pending.pop(request_id, None)
    return {"ok": True}


@app.get("/relay/result/{request_id}")
def get_result(request_id: str):
    with _lock:
        result = _results.pop(request_id, None)
    if result is None:
        return {"ready": False}
    return {"ready": True, "result": result}


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8081, log_level="warning")
