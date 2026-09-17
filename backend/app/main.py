from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import modbus_router
from app.services.modbus_service import ModbusError

app = FastAPI(title="Modbus 工业协议数据采集监控", version="1.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(modbus_router.router, prefix="/api")


@app.exception_handler(ModbusError)
async def modbus_error_handler(request: Request, exc: ModbusError):
    """Service-layer validation failures: explicit error envelope with a
    stable error code and a human-readable reason — never a fake success."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "failed", "error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Malformed request parameters (wrong type, missing field, etc.)."""
    details = exc.errors()
    message = "请求参数无效"
    if details:
        first = details[0]
        loc = ".".join(str(p) for p in first.get("loc", []) if p not in ("query", "path", "body"))
        message = f"参数 {loc}: {first.get('msg')}" if loc else first.get("msg", message)
    return JSONResponse(
        status_code=422,
        content={"status": "failed", "error": {"code": "INVALID_REQUEST", "message": message}},
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}
