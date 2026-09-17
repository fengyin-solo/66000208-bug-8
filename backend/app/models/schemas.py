from pydantic import BaseModel
from typing import List, Optional


class ModbusRegister(BaseModel):
    address: int
    name: str
    type: str
    value: float
    unit: str
    writable: bool = False


class Device(BaseModel):
    id: str
    name: str
    ip: str
    port: int
    slave_id: int
    online: bool
    registers: List[ModbusRegister] = []


# ---- API request bodies ----

class WriteRequest(BaseModel):
    value: Optional[int] = None


class ReadPoint(BaseModel):
    """Single point in a batch read. Fields are optional so malformed
    points are reported per-point instead of rejecting the whole batch."""
    device_id: Optional[str] = None
    address: Optional[int] = None
    count: Optional[int] = 1


class BatchReadRequest(BaseModel):
    points: List[ReadPoint]
