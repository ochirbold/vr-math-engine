import os
import secrets
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from ..expressions import ModelError
from ..storage import Conflict


def application(name):
    token = os.environ.get("SERVICE_TOKEN")
    if not token or len(token) < 16:
        raise RuntimeError("Set SERVICE_TOKEN to at least 16 characters")

    def authorize(x_service_token: str = Header(default="")):
        if not secrets.compare_digest(x_service_token, token):
            raise HTTPException(401, "Invalid service token")

    from .. import __version__
    app = FastAPI(title=name, version=__version__, dependencies=[Depends(authorize)])

    @app.exception_handler(ModelError)
    async def invalid_model(_, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(Conflict)
    async def conflict(_, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def invalid_data(_, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def missing(_, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.get("/health")
    def health():
        return {"status": "ok", "service": name, "version": __version__}

    return app
