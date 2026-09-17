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
    """业务错误统一为 {"success": false, "error_code": ..., "error": ...}，与成功响应明确区分。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error_code": exc.code, "error": exc.message, "details": exc.details},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """请求体/参数格式错误同样返回可识别的失败结构，而不是默认 422 文本。"""
    return JSONResponse(
        status_code=400,
        content={"success": False, "error_code": "INVALID_REQUEST", "error": "请求参数格式不正确", "details": exc.errors()},
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}
