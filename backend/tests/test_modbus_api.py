"""读数/下发接口的成功与失败行为测试。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import modbus_service as svc

client = TestClient(app)


@pytest.fixture(autouse=True)
def restore_state():
    """每个用例前恢复寄存器初值，避免写入互相干扰。"""
    yield
    # 重新从定义构建运行态
    svc._DEVICES.clear()
    svc._DEVICES.update(svc._build_state())


# ---------- 设备列表 ----------

def test_list_devices():
    r = client.get("/api/modbus/devices")
    assert r.status_code == 200
    devs = r.json()
    assert {d["id"] for d in devs} == {"dev1", "dev2", "dev3", "dev4"}
    assert "address_range" in devs[0]


# ---------- 读数：成功 ----------

def test_read_success_returns_real_current_value():
    r = client.get("/api/modbus/read/dev1/0/1")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["values"] == [256]
    assert body["count"] == 1


def test_read_range_success():
    r = client.get("/api/modbus/read/dev1/0/3")
    assert r.status_code == 200
    assert r.json()["values"] == [256, 623, 178]


# ---------- 读数：无效目标必须明确失败 ----------

def test_read_nonexistent_device_fails_with_reason():
    r = client.get("/api/modbus/read/dev_x/0/1")
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False
    assert body["error_code"] == "DEVICE_NOT_FOUND"
    assert "不存在" in body["error"]
    # 失败响应绝不带 values，无法被误认为真实读数
    assert "values" not in body


def test_read_offline_device_fails():
    r = client.get("/api/modbus/read/dev3/0/1")
    assert r.status_code == 503
    body = r.json()
    assert body["success"] is False
    assert body["error_code"] == "DEVICE_OFFLINE"
    assert "离线" in body["error"]


def test_read_unsupported_address_fails_instead_of_fake_values():
    r = client.get("/api/modbus/read/dev1/99/1")
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False
    assert body["error_code"] == "ADDRESS_NOT_SUPPORTED"
    assert body["details"]["supported_addresses"] == [0, 1, 2, 10]


def test_read_address_beyond_modbus_range_fails():
    r = client.get("/api/modbus/read/dev1/70000/1")
    assert r.status_code == 400
    assert r.json()["error_code"] == "ADDRESS_OUT_OF_RANGE"


def test_read_negative_address_fails():
    r = client.get("/api/modbus/read/dev1/-1/1")
    assert r.status_code in (400, 422)


# ---------- 读数：数量超限必须拒绝 ----------

@pytest.mark.parametrize("count", [0, 126, 99999])
def test_read_count_out_of_range_rejected(count):
    r = client.get(f"/api/modbus/read/dev1/0/{count}")
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False
    assert body["error_code"] == "INVALID_COUNT"
    assert "values" not in body


def test_read_range_crossing_gap_fails_not_fabricated():
    # dev1 地址 3~9 不存在，跨度读必须报错而不是编造数值
    r = client.get("/api/modbus/read/dev1/0/11")
    assert r.status_code == 400
    assert r.json()["error_code"] == "ADDRESS_NOT_SUPPORTED"


# ---------- 批量读：单点失败不影响其它点位 ----------

def test_batch_read_isolates_failures():
    payload = {"points": [
        {"device_id": "dev1", "address": 0},       # ok
        {"device_id": "dev_x", "address": 0},      # 设备不存在
        {"device_id": "dev1", "address": 77},      # 地址不支持
        {"device_id": "dev3", "address": 0},       # 设备离线
        {"device_id": "dev2", "address": 1},       # ok
    ]}
    r = client.post("/api/modbus/read/batch", json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert body["success_count"] == 2
    assert body["failure_count"] == 3
    assert body["success"] is False  # 有失败点时整体标记失败，但结果逐条可分辨

    ok0, bad_dev, bad_addr, offline, ok1 = body["results"]
    assert ok0["success"] is True and ok0["value"] == 256
    assert ok1["success"] is True and ok1["value"] == 12
    assert bad_dev["success"] is False and bad_dev["error_code"] == "DEVICE_NOT_FOUND"
    assert bad_addr["success"] is False and bad_addr["error_code"] == "ADDRESS_NOT_SUPPORTED"
    assert offline["success"] is False and offline["error_code"] == "DEVICE_OFFLINE"


def test_batch_read_all_success():
    r = client.post("/api/modbus/read/batch", json={"points": [
        {"device_id": "dev1", "address": 0}, {"device_id": "dev2", "address": 0}]})
    body = r.json()
    assert body["success"] is True
    assert body["failure_count"] == 0


def test_batch_read_empty_rejected():
    r = client.post("/api/modbus/read/batch", json={"points": []})
    assert r.status_code == 400
    assert r.json()["error_code"] == "INVALID_COUNT"


def test_batch_read_too_many_points_rejected():
    points = [{"device_id": "dev1", "address": 0}] * (svc.MAX_BATCH_POINTS + 1)
    r = client.post("/api/modbus/read/batch", json={"points": points})
    assert r.status_code == 400
    assert r.json()["error_code"] == "INVALID_COUNT"


# ---------- 下发：成功才更新，之后读数可见 ----------

def test_write_success_updates_value_and_readback():
    r = client.post("/api/modbus/write/dev1/10", json={"value": 2000})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["old_value"] == 1000
    assert body["value"] == 2000

    r2 = client.get("/api/modbus/read/dev1/10/1")
    assert r2.json()["values"] == [2000]


def test_write_coil_success():
    r = client.post("/api/modbus/write/dev4/10", json={"value": 1})
    assert r.status_code == 200
    assert r.json()["value"] == 1


# ---------- 下发：各类失败，且必须保留原值 ----------

def test_write_nonexistent_device_fails():
    r = client.post("/api/modbus/write/dev_x/10", json={"value": 1})
    assert r.status_code == 404
    assert r.json()["error_code"] == "DEVICE_NOT_FOUND"


def test_write_offline_device_fails():
    r = client.post("/api/modbus/write/dev3/10", json={"value": 100})
    assert r.status_code == 503
    assert r.json()["error_code"] == "DEVICE_OFFLINE"


def test_write_unsupported_address_fails():
    r = client.post("/api/modbus/write/dev1/77", json={"value": 1})
    assert r.status_code == 400
    assert r.json()["error_code"] == "ADDRESS_NOT_SUPPORTED"


def test_write_readonly_register_fails_and_keeps_value():
    before = client.get("/api/modbus/read/dev1/0/1").json()["values"][0]
    r = client.post("/api/modbus/write/dev1/0", json={"value": 999})
    assert r.status_code == 400
    assert r.json()["error_code"] == "REGISTER_READ_ONLY"
    after = client.get("/api/modbus/read/dev1/0/1").json()["values"][0]
    assert after == before


def test_write_value_out_of_uint16_fails_and_keeps_value():
    assert client.post("/api/modbus/write/dev1/10", json={"value": 2000}).status_code == 200
    for bad in (-1, 65536, 999999):
        r = client.post("/api/modbus/write/dev1/10", json={"value": bad})
        assert r.status_code == 400
        assert r.json()["error_code"] == "INVALID_VALUE"
    # 原值 2000 必须保留
    assert client.get("/api/modbus/read/dev1/10/1").json()["values"] == [2000]


def test_write_value_out_of_register_range_fails():
    # dev1/10 采样间隔允许 100~60000
    r = client.post("/api/modbus/write/dev1/10", json={"value": 50})
    assert r.status_code == 400
    body = r.json()
    assert body["error_code"] == "INVALID_VALUE"
    assert body["details"]["min"] == 100
    assert client.get("/api/modbus/read/dev1/10/1").json()["values"] == [1000]


def test_write_non_integer_value_fails():
    r = client.post("/api/modbus/write/dev1/10", json={"value": "abc"})
    assert r.status_code == 400
    assert r.json()["error_code"] == "INVALID_VALUE"


def test_write_coil_rejects_non_binary_and_keeps_value():
    assert client.post("/api/modbus/write/dev4/10", json={"value": 1}).status_code == 200
    r = client.post("/api/modbus/write/dev4/10", json={"value": 5})
    assert r.status_code == 400
    assert r.json()["error_code"] == "INVALID_VALUE"
    # 失败保留原值 1
    assert client.get("/api/modbus/read/dev4/10/1").status_code == 400  # 线圈不能用保持寄存器读
    from app.services.modbus_service import _DEVICES
    assert _DEVICES["dev4"]["registers"][10]["value"] == 1


def test_write_missing_body_is_clear_failure():
    r = client.post("/api/modbus/write/dev1/10", json={})
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False
    assert body["error_code"] == "INVALID_REQUEST"
