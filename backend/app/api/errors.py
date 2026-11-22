"""RFC 9457 problem details for every error response."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.status import HTTP_422_UNPROCESSABLE_CONTENT

PROBLEM_JSON = "application/problem+json"


def _problem(status: int, title: str, detail: object, instance: str, **extra) -> JSONResponse:
    body = {"type": "about:blank", "title": title, "status": status, "detail": detail}
    body["instance"] = instance
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON)


def install(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        from http import HTTPStatus

        response = _problem(
            exc.status_code, HTTPStatus(exc.status_code).phrase, exc.detail, request.url.path
        )
        for key, value in (exc.headers or {}).items():
            response.headers[key] = value
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return _problem(
            HTTP_422_UNPROCESSABLE_CONTENT,
            "Unprocessable Content",
            "Request validation failed",
            request.url.path,
            errors=errors,
        )
