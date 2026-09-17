"""Modbus service.

Maintains an in-memory image of the registers exposed by every known
device. Reads return the current image values (so writes are reflected in
subsequent reads); writes mutate the image only after every precondition
has been validated. All invalid requests raise :class:`ModbusError` with an
explicit error code and human-readable reason instead of fabricating data.
"""
import threading
from typing import Any, Dict, List

# Modbus PDU limit: function 0x03 allows at most 125 holding registers
# in a single request.
MAX_READ_COUNT = 125
MIN_ADDRESS = 0
MAX_ADDRESS = 65535
MIN_REGISTER_VALUE = 0
MAX_REGISTER_VALUE = 65535


class ModbusError(Exception):
    """A request that must be reported to the caller as a failure.

    ``code`` is a stable machine-readable error code; ``status_code`` is the
    HTTP status the router should use; ``message`` explains the reason.
    """

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _reg(address: int, name: str, reg_type: str, value: int,
         unit: str, writable: bool = False,
         min_value: int = MIN_REGISTER_VALUE,
         max_value: int = MAX_REGISTER_VALUE,
         scale: float = 1.0) -> Dict[str, Any]:
    return {
        "address": address,
        "name": name,
        "type": reg_type,
        "value": value,
        "unit": unit,
        "writable": writable,
        "min_value": min_value,
        "max_value": max_value,
        "scale": scale,
    }


# Device register table. In production these values are refreshed from a
# pymodbus client; the table defines the set of addresses that exist.
_DEVICE_TABLE: Dict[str, Dict[str, Any]] = {
    "dev1": {
        "name": "温湿度传感器-A区", "ip": "192.168.1.101", "port": 502,
        "slave_id": 1, "online": True,
        "registers": [
            _reg(0, "温度", "holding", 2560, "°C", scale=0.01),
            _reg(1, "湿度", "holding", 6230, "%RH", scale=0.01),
            _reg(2, "露点", "holding", 1780, "°C", scale=0.01),
            _reg(3, "温度设定", "holding", 2600, "°C", writable=True,
                 min_value=0, max_value=10000, scale=0.01),
        ],
    },
    "dev2": {
        "name": "压力变送器-B区", "ip": "192.168.1.102", "port": 502,
        "slave_id": 2, "online": True,
        "registers": [
            _reg(0, "管道压力", "holding", 345, "MPa", scale=0.01),
            _reg(1, "差压", "holding", 12, "kPa", scale=0.01),
            _reg(2, "压力上限设定", "holding", 1000, "kPa", writable=True,
                 min_value=0, max_value=2500, scale=0.01),
        ],
    },
    "dev3": {
        "name": "电机控制器-C区", "ip": "192.168.1.103", "port": 502,
        "slave_id": 3, "online": False,
        "registers": [
            _reg(0, "转速", "holding", 1480, "RPM"),
            _reg(1, "电流", "holding", 125, "A", scale=0.1),
            _reg(2, "运行状态", "coil", 0, ""),
            _reg(3, "转速设定", "holding", 1500, "RPM", writable=True,
                 min_value=0, max_value=3000),
        ],
    },
    "dev4": {
        "name": "流量计-D区", "ip": "192.168.1.104", "port": 502,
        "slave_id": 4, "online": True,
        "registers": [
            _reg(0, "瞬时流量", "holding", 1567, "L/min", scale=0.1),
            _reg(1, "累计流量", "holding", 98234, "L"),
        ],
    },
}

_lock = threading.Lock()


def _public_device(device_id: str, device: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": device_id,
        "name": device["name"],
        "ip": device["ip"],
        "port": device["port"],
        "slave_id": device["slave_id"],
        "online": device["online"],
        "registers": [dict(r) for r in device["registers"]],
    }


def get_device_status() -> List[Dict[str, Any]]:
    """Return all known devices, including their register map."""
    return [_public_device(did, dev) for did, dev in _DEVICE_TABLE.items()]


def _get_device(device_id: str) -> Dict[str, Any]:
    device = _DEVICE_TABLE.get(device_id)
    if device is None:
        raise ModbusError(
            "DEVICE_NOT_FOUND",
            f"设备不存在: {device_id}",
            status_code=404,
        )
    return device


def _require_online(device_id: str, device: Dict[str, Any]) -> None:
    if not device["online"]:
        raise ModbusError(
            "DEVICE_OFFLINE",
            f"设备离线，无法访问: {device_id} ({device['name']})",
            status_code=503,
        )


def _validate_count(count: Any) -> int:
    if isinstance(count, bool) or not isinstance(count, int):
        raise ModbusError(
            "INVALID_COUNT",
            f"读取数量必须是整数，收到: {count!r}",
        )
    if count < 1:
        raise ModbusError(
            "INVALID_COUNT",
            f"读取数量必须 >= 1，收到: {count}",
        )
    if count > MAX_READ_COUNT:
        raise ModbusError(
            "COUNT_OUT_OF_RANGE",
            f"读取数量超出允许范围: {count}，单次最多读取 {MAX_READ_COUNT} 个寄存器",
        )
    return count


def _validate_address(address: Any, device: Dict[str, Any],
                      count: int) -> int:
    if isinstance(address, bool) or not isinstance(address, int):
        raise ModbusError(
            "INVALID_ADDRESS",
            f"寄存器地址必须是非负整数，收到: {address!r}",
        )
    if address < MIN_ADDRESS:
        raise ModbusError(
            "ADDRESS_OUT_OF_RANGE",
            f"寄存器地址不能为负数: {address}",
        )
    if address > MAX_ADDRESS:
        raise ModbusError(
            "ADDRESS_OUT_OF_RANGE",
            f"寄存器地址超出 Modbus 地址范围 (0-{MAX_ADDRESS}): {address}",
        )
    register_count = len(device["registers"])
    end = address + count
    if end > register_count:
        raise ModbusError(
            "ADDRESS_OUT_OF_RANGE",
            (f"读取范围超出设备 {device['name']} 的寄存器区间: "
             f"起始地址 {address}，数量 {count}，结束地址 {end}，"
             f"该设备有效地址为 0-{register_count - 1}"),
        )
    return address


def _read_result(device_id: str, device: Dict[str, Any],
                 address: int, count: int) -> Dict[str, Any]:
    window = device["registers"][address:address + count]
    return {
        "status": "success",
        "device_id": device_id,
        "address": address,
        "count": count,
        # Raw 16-bit register words, as transported over Modbus.
        "values": [r["value"] for r in window],
        # Engineering values after per-register scaling (value * scale).
        "engineering_values": [
            round(r["value"] * r["scale"], 4) for r in window
        ],
        "points": [
            {
                "address": r["address"],
                "name": r["name"],
                "unit": r["unit"],
                "writable": r["writable"],
                "raw_value": r["value"],
                "value": round(r["value"] * r["scale"], 4),
            }
            for r in window
        ],
    }


def read_registers(device_id: str, address: int, count: int = 1) -> Dict[str, Any]:
    """Read holding registers. Raises ModbusError on any invalid request."""
    device = _get_device(device_id)
    count = _validate_count(count)
    _validate_address(address, device, count)
    _require_online(device_id, device)

    with _lock:
        return _read_result(device_id, device, address, count)


def read_batch(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Read many points in one request.

    Each point is validated independently: a failure on one point never
    prevents the remaining points from being read.
    """
    results: List[Dict[str, Any]] = []
    for idx, point in enumerate(points):
        device_id = point.get("device_id")
        address = point.get("address")
        count = point.get("count", 1)
        try:
            device = _get_device(device_id)
            count = _validate_count(count)
            _validate_address(address, device, count)
            _require_online(device_id, device)
            with _lock:
                result = _read_result(device_id, device, address, count)
            result["index"] = idx
            results.append(result)
        except ModbusError as exc:
            results.append({
                "index": idx,
                "status": "failed",
                "device_id": device_id,
                "address": address,
                "count": count,
                "error": {"code": exc.code, "message": exc.message},
            })
    return results


def write_register(device_id: str, address: int, value: Any) -> Dict[str, Any]:
    """Write one holding register.

    Every precondition (device, address, type, writability, range) is
    checked before the stored value is touched, so a failed write leaves
    the previous register value intact.
    """
    device = _get_device(device_id)
    _require_online(device_id, device)

    if isinstance(value, bool) or not isinstance(value, int):
        raise ModbusError(
            "INVALID_VALUE",
            f"写入值必须是整数，收到: {value!r}",
        )
    if not (MIN_REGISTER_VALUE <= value <= MAX_REGISTER_VALUE):
        raise ModbusError(
            "VALUE_OUT_OF_RANGE",
            f"写入值超出 16 位寄存器范围 (0-65535): {value}",
        )
    if isinstance(address, bool) or not isinstance(address, int) or address < 0:
        raise ModbusError(
            "INVALID_ADDRESS",
            f"寄存器地址必须是非负整数，收到: {address!r}",
        )

    registers = device["registers"]
    if address >= len(registers):
        raise ModbusError(
            "ADDRESS_OUT_OF_RANGE",
            (f"写入地址超出设备 {device['name']} 的寄存器区间: {address}，"
             f"该设备有效地址为 0-{len(registers) - 1}"),
        )

    register = registers[address]
    if register["type"] != "holding":
        raise ModbusError(
            "REGISTER_NOT_WRITABLE",
            f"地址 {address} ({register['name']}) 不是保持寄存器，不支持单点写入",
        )
    if not register["writable"]:
        raise ModbusError(
            "REGISTER_NOT_WRITABLE",
            f"地址 {address} ({register['name']}) 为只读寄存器，禁止写入",
        )
    if not (register["min_value"] <= value <= register["max_value"]):
        raise ModbusError(
            "VALUE_OUT_OF_RANGE",
            (f"写入值超出寄存器 {register['name']} 的允许范围 "
             f"({register['min_value']}-{register['max_value']}): {value}"),
        )

    with _lock:
        old_value = register["value"]
        register["value"] = value
        new_value = register["value"]

    return {
        "status": "success",
        "device_id": device_id,
        "address": address,
        "value": new_value,
        "previous_value": old_value,
    }
