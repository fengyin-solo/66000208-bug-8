from pydantic import BaseModel, Field
from typing import Any, List, Optional


class BatchReadPoint(BaseModel):
    device_id: str
    address: int


class BatchReadRequest(BaseModel):
    points: List[BatchReadPoint] = Field(..., description="待读取点位列表")


class WriteRequest(BaseModel):
    value: Any = Field(..., description="写入值：保持寄存器为整数(uint16)，线圈为 0/1")
