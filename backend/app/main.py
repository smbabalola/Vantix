from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .api import router

app = FastAPI(title="Vantix API", version="0.1.0")
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = request.headers.get("X-Correlation-ID", "unavailable")
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred.",
            "correlation_id": correlation_id,
            "details": {},
        },
    )
