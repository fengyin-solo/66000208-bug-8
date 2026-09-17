from fastapi import APIRouter
from app.models.schemas import BatchReadRequest, WriteRequest
from app.services import modbus_service as svc
from app.services.modbus_service import read_registers, read_batch, write_register, get_device_status

router = APIRouter()


@router.get("/modbus/devices")
def list_devices():
    return get_device_status()


@router.get("/modbus/read/{device_id}/{address}/{count}")
def read_holding(device_id: str, address: int, count: int = 1):
    """读取保持寄存器。目标不存在/地址无效/数量超范围都会明确失败并说明原因。"""
    return read_registers(device_id, address, count)


@router.post("/modbus/read/batch")
def read_holding_batch(req: BatchReadRequest):
    """批量读取点位，单点失败不影响其它点位，逐点返回成功/失败。"""
    return read_batch([p.model_dump() for p in req.points])


@router.post("/modbus/write/{device_id}/{address}")
def write_register_endpoint(device_id: str, address: int, req: WriteRequest):
    """下发写值。失败时原值保留并返回 success=false 及原因；成功才更新当前值。"""
    return write_register(device_id, address, req.value)
