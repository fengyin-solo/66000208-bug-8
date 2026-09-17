"""API tests for the Modbus read/write endpoints.

Covers: invalid device/address/count rejection with reasons, write failure
leaves the old value intact, success vs failure envelopes are distinct,
and batch per-point failure isolation.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import modbus_service as svc

client = TestClient(app)


@pytest.fixture(autouse=True)
def restore_register_image():
    """Snapshot/restore the in-memory register image around every test."""
    snapshot = {
        did: [dict(r) for r in dev["registers"]]
        for did, dev in svc._DEVICE_TABLE.items()
    }
    yield
    for did, regs in snapshot.items():
        svc._DEVICE_TABLE[did]["registers"] = [dict(r) for r in regs]


# ---------------- reads ----------------

def test_read_success_returns_real_stored_values():
    r = client.get("/api/modbus/read/dev1/0/1")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["values"] == [2560]
    assert body["count"] == 1


def test_read_range_success():
    r = client.get("/api/modbus/read/dev1/0/3")
    assert r.status_code == 200
    assert r.json()["values"] == [2560, 6230, 1780]


def test_read_is_deterministic_not_random():
    first = client.get("/api/modbus/read/dev2/0/2").json()["values"]
    second = client.get("/api/modbus/read/dev2/0/2").json()["values"]
    assert first == second == [345, 12]


def test_read_unknown_device_fails_with_reason():
    r = client.get("/api/modbus/read/dev-xxx/0/1")
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "DEVICE_NOT_FOUND"
    assert "dev-xxx" in body["error"]["message"]


def test_read_address_far_beyond_range_rejected():
    r = client.get("/api/modbus/read/dev1/999999/1")
    assert r.status_code == 400
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "ADDRESS_OUT_OF_RANGE"


def test_read_span_crossing_device_window_rejected():
    # dev1 only has addresses 0-3; starting at 3 with count 2 ends at 5
    r = client.get("/api/modbus/read/dev1/3/2")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "ADDRESS_OUT_OF_RANGE"


def test_read_negative_address_rejected():
    r = client.get("/api/modbus/read/dev1/-1/1")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "ADDRESS_OUT_OF_RANGE"


def test_read_huge_count_rejected():
    r = client.get("/api/modbus/read/dev1/0/100000")
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "COUNT_OUT_OF_RANGE"
    assert "125" in body["error"]["message"]


def test_read_zero_count_rejected():
    r = client.get("/api/modbus/read/dev1/0/0")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_COUNT"


def test_read_non_integer_address_is_422_envelope():
    r = client.get("/api/modbus/read/dev1/abc/1")
    assert r.status_code == 422
    assert r.json()["status"] == "failed"
    assert r.json()["error"]["code"] == "INVALID_REQUEST"


def test_read_offline_device_fails():
    r = client.get("/api/modbus/read/dev3/0/1")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "DEVICE_OFFLINE"


def test_read_reflects_successful_write():
    r = client.post("/api/modbus/write/dev1/3?value=2710")
    assert r.status_code == 200
    r = client.get("/api/modbus/read/dev1/3/1")
    assert r.json()["values"] == [2710]


# ---------------- writes ----------------

def test_write_success_via_query_param():
    r = client.post("/api/modbus/write/dev1/3?value=2710")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["value"] == 2710
    assert body["previous_value"] == 2600


def test_write_success_via_json_body():
    r = client.post("/api/modbus/write/dev2/2", json={"value": 1500})
    assert r.status_code == 200
    assert r.json()["value"] == 1500


def test_write_unknown_device_fails():
    r = client.post("/api/modbus/write/dev-xxx/0?value=1")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "DEVICE_NOT_FOUND"


def test_write_offline_device_fails():
    r = client.post("/api/modbus/write/dev3/3?value=1600")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "DEVICE_OFFLINE"


def test_write_read_only_register_fails_and_keeps_old_value():
    before = client.get("/api/modbus/read/dev1/0/1").json()["values"][0]
    r = client.post("/api/modbus/write/dev1/0?value=9999")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "REGISTER_NOT_WRITABLE"
    after = client.get("/api/modbus/read/dev1/0/1").json()["values"][0]
    assert after == before == 2560


def test_write_address_beyond_range_fails():
    r = client.post("/api/modbus/write/dev1/99?value=1")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "ADDRESS_OUT_OF_RANGE"


def test_write_value_over_16bit_rejected():
    r = client.post("/api/modbus/write/dev1/3", json={"value": 70000})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALUE_OUT_OF_RANGE"
    # old value untouched
    assert client.get("/api/modbus/read/dev1/3/1").json()["values"] == [2600]


def test_write_negative_value_rejected():
    r = client.post("/api/modbus/write/dev1/3", json={"value": -1})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALUE_OUT_OF_RANGE"
    assert client.get("/api/modbus/read/dev1/3/1").json()["values"] == [2600]


def test_write_outside_register_specific_range_rejected():
    # 温度设定 allows 0-10000
    r = client.post("/api/modbus/write/dev1/3", json={"value": 50000})
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "VALUE_OUT_OF_RANGE"
    assert "温度设定" in body["error"]["message"]
    assert client.get("/api/modbus/read/dev1/3/1").json()["values"] == [2600]


def test_write_without_value_fails():
    r = client.post("/api/modbus/write/dev1/3")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_VALUE"


def test_write_non_integer_value_is_422_envelope():
    r = client.post("/api/modbus/write/dev1/3?value=abc")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_REQUEST"


# ---------------- batch reads ----------------

def test_batch_all_success():
    r = client.post("/api/modbus/read/batch", json={"points": [
        {"device_id": "dev1", "address": 0, "count": 1},
        {"device_id": "dev2", "address": 1, "count": 1},
    ]})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "success"
    assert body["succeeded"] == 2
    assert body["failed"] == 0
    assert all(x["status"] == "success" for x in body["results"])
    assert body["results"][0]["values"] == [2560]
    assert body["results"][1]["values"] == [12]


def test_batch_failures_are_isolated_from_other_points():
    r = client.post("/api/modbus/read/batch", json={"points": [
        {"device_id": "dev1", "address": 0, "count": 1},        # ok
        {"device_id": "dev-xxx", "address": 0, "count": 1},     # no device
        {"device_id": "dev1", "address": 0, "count": 99999},    # bad count
        {"device_id": "dev1", "address": 999, "count": 1},      # bad address
        {"device_id": "dev3", "address": 0, "count": 1},        # offline
    ]})
    assert r.status_code == 200  # batch itself accepted; failures are per-point
    body = r.json()
    assert body["status"] == "partial"
    assert body["succeeded"] == 1
    assert body["failed"] == 4

    results = body["results"]
    assert results[0]["status"] == "success"
    assert results[0]["values"] == [2560]

    assert results[1]["status"] == "failed"
    assert results[1]["error"]["code"] == "DEVICE_NOT_FOUND"
    assert results[2]["error"]["code"] == "COUNT_OUT_OF_RANGE"
    assert results[3]["error"]["code"] == "ADDRESS_OUT_OF_RANGE"
    assert results[4]["error"]["code"] == "DEVICE_OFFLINE"

    # each failed point still carries its identity for correlation
    assert results[1]["device_id"] == "dev-xxx"
    assert [x["index"] for x in results] == [0, 1, 2, 3, 4]


def test_batch_all_failed_reports_failed_status():
    r = client.post("/api/modbus/read/batch", json={"points": [
        {"device_id": "dev-xxx", "address": 0, "count": 1},
    ]})
    assert r.json()["status"] == "failed"
    assert r.json()["succeeded"] == 0


def test_batch_malformed_point_does_not_kill_batch():
    r = client.post("/api/modbus/read/batch", json={"points": [
        {"address": 0, "count": 1},                          # missing device_id
        {"device_id": "dev1", "address": 0, "count": 1},     # ok
    ]})
    assert r.status_code == 200
    results = r.json()["results"]
    assert results[0]["status"] == "failed"
    assert results[0]["error"]["code"] == "DEVICE_NOT_FOUND"
    assert results[1]["status"] == "success"
