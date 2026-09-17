from fastapi import APIRouter

from app.models.schemas import BatchReadRequest, WriteRequest
from app.services.modbus_service import (
    get_device_status,
    read_batch,
    read_registers,
    write_register,
)

router = APIRouter()


@router.get("/modbus/devices")
def list_devices():
    return get_device_status()


@router.get("/modbus/read/{device_id}/{address}/{count}")
def read_holding(device_id: str, address: int, count: int = 1):
    """Read holding registers from a Modbus device.

    Fails explicitly (4xx/5xx with an error code) when the device does not
    exist, is offline, the address range is invalid, or the count exceeds
    the permitted maximum.
    """
    return read_registers(device_id, address, count)


@router.post("/modbus/read/batch")
def read_holding_batch(request: BatchReadRequest):
    """Read many points in one call.

    Each point is validated independently: failed points are returned with
    status=failed plus an error code/reason and do not affect other points.
    """
    results = read_batch([p.model_dump() for p in request.points])
    succeeded = sum(1 for r in results if r["status"] == "success")
    return {
        "status": "success" if succeeded == len(results) else (
            "failed" if succeeded == 0 else "partial"
        ),
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


@router.post("/modbus/write/{device_id}/{address}")
def write_register_endpoint(
    device_id: str,
    address: int,
    value: int | None = None,
    payload: WriteRequest | None = None,
):
    """Write one holding register.

    Accepts the value either as a query parameter (?value=123) or in a
    JSON body ({"value": 123}). Nothing is mutated until every check
    passes; on failure the previous register value is preserved and the
    response carries an explicit error code/reason.
    """
    raw_value = value if value is not None else (payload.value if payload else None)
    return write_register(device_id, address, raw_value)
