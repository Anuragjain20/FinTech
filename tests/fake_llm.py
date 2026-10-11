"""Fake OpenAI-compatible chat server that records requests and replies with whatever the test sets."""
import json
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def hash_vector(text: str, dims: int = 64) -> list[float]:
    """Deterministic bag-of-words vector: texts sharing words are close (stable across processes, unlike hash())."""
    import hashlib
    import re
    v = [0.0] * dims
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dims] += 1.0  # noqa: S324
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


class FakeLLM:
    def __init__(self):
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.embed_requests: list[dict] = []
        self.reply = lambda req: {"issues": []}
        self.fail = False
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
        self.base_url = f"http://127.0.0.1:{port}/v1"
        app = FastAPI()

        @app.post("/v1/chat/completions")
        async def chat(request: Request):
            body = await request.json()
            self.requests.append(body)
            self.headers.append(dict(request.headers))
            if self.fail:
                return JSONResponse({"error": "boom"}, status_code=500)
            content = self.reply(body)
            return {"id": "x", "object": "chat.completion", "model": body.get("model"),
                    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant",
                                 "content": content if isinstance(content, str) else json.dumps(content)}}],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}}

        @app.post("/v1/embeddings")
        async def embeddings(request: Request):
            body = await request.json()
            self.embed_requests.append({**body, "_auth": request.headers.get("authorization")})
            inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
            return {"object": "list", "model": body.get("model"), "usage": {"prompt_tokens": 1, "total_tokens": 1},
                    "data": [{"object": "embedding", "index": i, "embedding": hash_vector(t)} for i, t in enumerate(inputs)]}

        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("fake LLM did not start")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(5)
