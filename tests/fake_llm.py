"""Fake OpenAI-compatible chat server that records requests and replies with whatever the test sets."""
import json
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class FakeLLM:
    def __init__(self):
        self.requests: list[dict] = []
        self.reply = lambda req: {"issues": []}
        self.fail = False
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
        self.base_url = f"http://127.0.0.1:{port}/v1"
        app = FastAPI()

        @app.post("/v1/chat/completions")
        async def chat(request: Request):
            body = await request.json()
            self.requests.append(body)
            if self.fail:
                return JSONResponse({"error": "boom"}, status_code=500)
            content = self.reply(body)
            return {"choices": [{"message": {"role": "assistant", "content": content if isinstance(content, str) else json.dumps(content)}}]}

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
