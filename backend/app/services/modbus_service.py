"""Modbus service.

当前为带寄存器地址表的内存模拟实现，生产环境可把
``_device_read`` / ``_device_write`` 替换为 pymodbus 调用，
外层的参数校验、错误分类与结果结构保持不变。
"""
import threading
from typing import Any, Dict, List, Optional

# Modbus 协议层面的硬限制（功能码 0x03/0x06/0x10）
MAX_REGISTER_ADDRESS = 65535
MAX_READ_COUNT = 125
# 批量读接口一次允许提交的点位上限（防止超大请求拖垮采集服务）
MAX_BATCH_POINTS = 100

UINT16_MIN = 0
UINT16_MAX = 65535


class ModbusError(Exception):
    """所有业务错误的基类，携带错误码、HTTP 状态码与面向用户的原因。"""

    code = "MODBUS_ERROR"
    status_code = 400

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class DeviceNotFoundError(ModbusError):
    code = "DEVICE_NOT_FOUND"
    status_code = 404


class DeviceOfflineError(ModbusError):
    code = "DEVICE_OFFLINE"
    status_code = 503


class AddressOutOfRangeError(ModbusError):
    code = "ADDRESS_OUT_OF_RANGE"
    status_code = 400


class AddressNotSupportedError(ModbusError):
    code = "ADDRESS_NOT_SUPPORTED"
    status_code = 400


class InvalidCountError(ModbusError):
    code = "INVALID_COUNT"
    status_code = 400


class InvalidValueError(ModbusError):
    code = "INVALID_VALUE"
    status_code = 400


class RegisterReadOnlyError(ModbusError):
    code = "REGISTER_READ_ONLY"
    status_code = 400


# 寄存器定义：address/name/type/writable/value 范围
# type 为 holding(保持寄存器) 或 coil(线圈)
_DEVICE_DEFS: List[Dict[str, Any]] = [
    {
        "id": "dev1", "name": "温湿度传感器-A区", "ip": "192.168.1.101",
        "port": 502, "slave_id": 1, "online": True,
        "registers": [
            {"address": 0, "name": "温度", "type": "holding", "unit": "°C", "writable": False, "value": 256, "min": -400, "max": 1250},
            {"address": 1, "name": "湿度", "type": "holding", "unit": "%RH", "writable": False, "value": 623, "min": 0, "max": 1000},
            {"address": 2, "name": "露点", "type": "holding", "unit": "°C", "writable": False, "value": 178, "min": -400, "max": 1250},
            {"address": 10, "name": "采样间隔", "type": "holding", "unit": "ms", "writable": True, "value": 1000, "min": 100, "max": 60000},
        ],
    },
    {
        "id": "dev2", "name": "压力变送器-B区", "ip": "192.168.1.102",
        "port": 502, "slave_id": 2, "online": True,
        "registers": [
            {"address": 0, "name": "管道压力", "type": "holding", "unit": "MPa", "writable": False, "value": 345, "min": 0, "max": 2500},
            {"address": 1, "name": "差压", "type": "holding", "unit": "kPa", "writable": False, "value": 12, "min": 0, "max": 500},
            {"address": 10, "name": "量程上限", "type": "holding", "unit": "MPa", "writable": True, "value": 1000, "min": 0, "max": 2500},
        ],
    },
    {
        "id": "dev3", "name": "电机控制器-C区", "ip": "192.168.1.103",
        "port": 502, "slave_id": 3, "online": False,
        "registers": [
            {"address": 0, "name": "转速", "type": "holding", "unit": "RPM", "writable": False, "value": 1480, "min": 0, "max": 3000},
            {"address": 1, "name": "电流", "type": "holding", "unit": "A", "writable": False, "value": 125, "min": 0, "max": 650},
            {"address": 2, "name": "运行状态", "type": "coil", "unit": "", "writable": True, "value": 0},
            {"address": 10, "name": "频率给定", "type": "holding", "unit": "Hz", "writable": True, "value": 500, "min": 0, "max": 600},
            {"address": 11, "name": "启停命令", "type": "coil", "unit": "", "writable": True, "value": 0},
        ],
    },
    {
        "id": "dev4", "name": "流量计-D区", "ip": "192.168.1.104",
        "port": 502, "slave_id": 4, "online": True,
        "registers": [
            {"address": 0, "name": "瞬时流量", "type": "holding", "unit": "L/min", "writable": False, "value": 1567, "min": 0, "max": 10000},
            {"address": 1, "name": "累计流量", "type": "holding", "unit": "L", "writable": False, "value": 98234, "min": 0, "max": 65535},
            {"address": 10, "name": "清零累计", "type": "coil", "unit": "", "writable": True, "value": 0},
        ],
    },
]


def _build_state() -> Dict[str, Dict[str, Any]]:
    """根据设备定义初始化运行态（含当前寄存器值，写入只改这里）。"""
    state: Dict[str, Dict[str, Any]] = {}
    for dev in _DEVICE_DEFS:
        reg_map: Dict[int, Dict[str, Any]] = {}
        for reg in dev["registers"]:
            reg_map[reg["address"]] = {
                "address": reg["address"],
                "name": reg["name"],
                "type": reg["type"],
                "unit": reg.get("unit", ""),
                "writable": reg["writable"],
                "min": reg.get("min"),
                "max": reg.get("max"),
                "value": reg["value"],
            }
        state[dev["id"]] = {
            "id": dev["id"],
            "name": dev["name"],
            "ip": dev["ip"],
            "port": dev["port"],
            "slave_id": dev["slave_id"],
            "online": dev["online"],
            "registers": reg_map,
            "max_address": max(reg_map.keys()),
        }
    return state


_DEVICES: Dict[str, Dict[str, Any]] = _build_state()
_LOCK = threading.Lock()


def get_device_status() -> List[Dict[str, Any]]:
    """返回设备列表（不含寄存器明细，保持原接口形态）。"""
    return [
        {
            "id": d["id"],
            "name": d["name"],
            "ip": d["ip"],
            "port": d["port"],
            "slave_id": d["slave_id"],
            "online": d["online"],
            "address_range": [0, d["max_address"]],
        }
        for d in _DEVICES.values()
    ]


def _get_device(device_id: str) -> Dict[str, Any]:
    device = _DEVICES.get(device_id)
    if device is None:
        raise DeviceNotFoundError(
            f"设备 '{device_id}' 不存在",
            {"device_id": device_id, "available_device_ids": list(_DEVICES.keys())},
        )
    if not device["online"]:
        raise DeviceOfflineError(
            f"设备 '{device['name']}'({device_id}) 当前离线，无法访问",
            {"device_id": device_id},
        )
    return device


def _validate_address(address: int, device_id: str) -> None:
    if not isinstance(address, int) or isinstance(address, bool):
        raise AddressOutOfRangeError(
            "寄存器地址必须为整数", {"address": address}
        )
    if address < 0 or address > MAX_REGISTER_ADDRESS:
        raise AddressOutOfRangeError(
            f"寄存器地址 {address} 超出允许范围 0~{MAX_REGISTER_ADDRESS}",
            {"device_id": device_id, "address": address, "max_address": MAX_REGISTER_ADDRESS},
        )


def _get_register(device: Dict[str, Any], address: int) -> Dict[str, Any]:
    """取寄存器定义；地址合法但该设备上不存在时明确失败。"""
    _validate_address(address, device["id"])
    reg = device["registers"].get(address)
    if reg is None:
        raise AddressNotSupportedError(
            f"设备 '{device['name']}' 上不存在地址 {address}，"
            f"该设备可用地址: {sorted(device['registers'].keys())}",
            {
                "device_id": device["id"],
                "address": address,
                "supported_addresses": sorted(device["registers"].keys()),
            },
        )
    return reg


def read_registers(device_id: str, address: int, count: int = 1) -> Dict[str, Any]:
    """读取保持寄存器。

    目标设备、起始地址、数量任一不合法都抛出带原因的 ModbusError；
    全部校验通过后才返回真实的当前值（写入后可见更新）。
    """
    device = _get_device(device_id)
    _validate_address(address, device_id)

    if not isinstance(count, int) or isinstance(count, bool):
        raise InvalidCountError("读取数量必须为整数", {"count": count})
    if count < 1 or count > MAX_READ_COUNT:
        raise InvalidCountError(
            f"读取数量 {count} 超出允许范围 1~{MAX_READ_COUNT}",
            {"device_id": device_id, "count": count, "max_count": MAX_READ_COUNT},
        )
    if address + count - 1 > MAX_REGISTER_ADDRESS:
        raise AddressOutOfRangeError(
            f"读取区间 {address}~{address + count - 1} 越过 Modbus 地址上限 {MAX_REGISTER_ADDRESS}",
            {"device_id": device_id, "address": address, "count": count},
        )

    values: List[int] = []
    for offset in range(count):
        # 区间内每个地址独立校验：不支持的点位报错，绝不伪造数值
        reg = _get_register(device, address + offset)
        if reg["type"] != "holding":
            raise AddressNotSupportedError(
                f"地址 {address + offset} 是线圈/离散量，请使用对应位读取接口",
                {"device_id": device_id, "address": address + offset, "register_type": reg["type"]},
            )
        values.append(reg["value"])

    return {
        "success": True,
        "device_id": device_id,
        "address": address,
        "count": count,
        "values": values,
    }


def read_batch(points: List[Dict[str, int]]) -> Dict[str, Any]:
    """批量读取：每个点位独立成功/失败，单点失败不影响其它点位。"""
    if not isinstance(points, list) or len(points) == 0:
        raise InvalidCountError("批量读取点位列表不能为空", {"max_points": MAX_BATCH_POINTS})
    if len(points) > MAX_BATCH_POINTS:
        raise InvalidCountError(
            f"批量读取点位数量 {len(points)} 超过上限 {MAX_BATCH_POINTS}",
            {"count": len(points), "max_points": MAX_BATCH_POINTS},
        )

    results: List[Dict[str, Any]] = []
    success_count = 0
    failure_count = 0
    for idx, point in enumerate(points):
        device_id = point.get("device_id")
        address = point.get("address")
        result: Dict[str, Any] = {"index": idx, "device_id": device_id, "address": address}
        try:
            if not isinstance(device_id, str) or not isinstance(address, int) or isinstance(address, bool):
                raise ModbusError("点位必须包含字符串 device_id 和整数 address",
                                  {"device_id": device_id, "address": address})
            device = _get_device(device_id)
            reg = _get_register(device, address)
            if reg["type"] != "holding":
                raise AddressNotSupportedError(
                    f"地址 {address} 是线圈/离散量，请使用对应位读取接口",
                    {"register_type": reg["type"]},
                )
            result.update(success=True, name=reg["name"], value=reg["value"], unit=reg["unit"])
            success_count += 1
        except ModbusError as exc:
            result.update(success=False, error_code=exc.code, error=exc.message, details=exc.details)
            failure_count += 1
        results.append(result)

    return {
        "success": failure_count == 0,
        "total": len(results),
        "success_count": success_count,
        "failure_count": failure_count,
        "results": results,
    }


def _validate_write_value(reg: Dict[str, Any], value: Any) -> int:
    """按寄存器类型与量程校验写入值，返回规整后的值。"""
    reg_type = reg["type"]
    if isinstance(value, bool):
        value = int(value)
    if not isinstance(value, int):
        raise InvalidValueError(
            f"写入值必须是整数，收到: {value!r}", {"value": value}
        )

    if reg_type == "coil":
        if value not in (0, 1):
            raise InvalidValueError(
                f"线圈只接受 0/1（或 false/true），收到: {value}",
                {"address": reg["address"], "value": value, "allowed": [0, 1]},
            )
        return value

    # holding register：uint16
    if value < UINT16_MIN or value > UINT16_MAX:
        raise InvalidValueError(
            f"保持寄存器值 {value} 超出 uint16 范围 {UINT16_MIN}~{UINT16_MAX}",
            {"address": reg["address"], "value": value, "min": UINT16_MIN, "max": UINT16_MAX},
        )
    lo, hi = reg.get("min"), reg.get("max")
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise InvalidValueError(
            f"写入值 {value} 超出寄存器 '{reg['name']}' 允许范围 {lo}~{hi}",
            {"address": reg["address"], "value": value, "min": lo, "max": hi},
        )
    return value


def write_register(device_id: str, address: int, value: Any) -> Dict[str, Any]:
    """写入单个寄存器。

    设备/地址/值任一不合法都失败并说明原因；失败时寄存器原值保留不变。
    成功才更新当前值，随后读接口能读到新值。
    """
    with _LOCK:
        device = _get_device(device_id)
        reg = _get_register(device, address)

        if not reg["writable"]:
            raise RegisterReadOnlyError(
                f"寄存器 '{reg['name']}'(地址 {address}) 为只读测点，不允许下发",
                {"device_id": device_id, "address": address, "register_name": reg["name"]},
            )

        old_value = reg["value"]
        normalized = _validate_write_value(reg, value)

        # 全部校验通过后才落值
        reg["value"] = normalized

        return {
            "success": True,
            "device_id": device_id,
            "address": address,
            "register_name": reg["name"],
            "old_value": old_value,
            "value": normalized,
        }
