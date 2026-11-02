import json
import urllib.error
import urllib.request


class RemoteError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class Client:
    def __init__(self, base, token, timeout=100):
        self.base, self.token, self.timeout = base.rstrip("/"), token, timeout

    def call(self, method, path, payload=None):
        body = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
        request = urllib.request.Request(self.base + path, data=body, method=method,
                                         headers={"Content-Type": "application/json", "X-Service-Token": self.token})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RemoteError(exc.code, exc.read().decode()[:2000]) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RemoteError(503, str(exc)) from exc
