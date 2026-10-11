"""A minimal but real OpenID Provider (discovery, authorize, token with PKCE check, JWKS) for tests."""
import base64
import hashlib
import socket
import threading
import time
from urllib.parse import urlencode

import uvicorn
from authlib.jose import JsonWebKey, jwt
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

KEY = JsonWebKey.generate_key("RSA", 2048, is_private=True, options={"kid": "k1"})
CLIENT_ID, CLIENT_SECRET = "fintech", "s3cret"


class Idp:
    def __init__(self):
        self.user = {"email": "alice@acme.test", "email_verified": True}
        self.codes: dict = {}
        sock = socket.socket(); sock.bind(("127.0.0.1", 0)); self.port = sock.getsockname()[1]; sock.close()
        self.issuer = f"http://127.0.0.1:{self.port}"
        self.app = self._build()
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def _build(self) -> FastAPI:
        app = FastAPI()

        @app.get("/.well-known/openid-configuration")
        def discovery():
            return {"issuer": self.issuer, "authorization_endpoint": f"{self.issuer}/authorize", "token_endpoint": f"{self.issuer}/token",
                    "jwks_uri": f"{self.issuer}/jwks", "response_types_supported": ["code"], "subject_types_supported": ["public"],
                    "id_token_signing_alg_values_supported": ["RS256"], "code_challenge_methods_supported": ["S256"]}

        @app.get("/jwks")
        def jwks():
            return {"keys": [KEY.as_dict(is_private=False)]}

        @app.get("/authorize")
        def authorize(request: Request):
            q = request.query_params
            code = f"code{len(self.codes)}"
            self.codes[code] = {"nonce": q.get("nonce"), "challenge": q.get("code_challenge"), "user": dict(self.user),
                                "redirect_uri": q["redirect_uri"]}
            return RedirectResponse(f"{q['redirect_uri']}?{urlencode({'code': code, 'state': q['state']})}")

        @app.post("/token")
        def token(code: str = Form(...), code_verifier: str = Form(""), client_id: str = Form(CLIENT_ID),
                  client_secret: str = Form(CLIENT_SECRET), redirect_uri: str = Form(""), grant_type: str = Form("")):
            c = self.codes.pop(code, None)
            if not c or client_secret != CLIENT_SECRET:
                raise HTTPException(400, "invalid_grant")
            digest = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).rstrip(b"=").decode()
            if digest != c["challenge"]:
                raise HTTPException(400, "pkce mismatch")
            now = int(time.time())
            claims = {"iss": self.issuer, "aud": CLIENT_ID, "sub": "u-" + c["user"]["email"], "iat": now, "exp": now + 300,
                      "nonce": c["nonce"], **c["user"]}
            idt = jwt.encode({"alg": "RS256", "kid": "k1"}, claims, KEY).decode()
            return {"access_token": "at", "token_type": "Bearer", "id_token": idt, "expires_in": 300}

        return app

    def start(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("fake IdP did not start")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(5)
