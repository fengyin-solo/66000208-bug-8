# solo-6600020: Modbus 工业协议数据采集监控大屏

## 技术栈
- Frontend: Vue 3 + TypeScript + Vite + Pinia + Tailwind CSS + ECharts
- Backend: Python FastAPI + pymodbus

## 核心特性
1. **Modbus RTU/TCP 寄存器实时读取**：pymodbus 连接工业设备
2. **时序曲线 ECharts 绘制**：实时趋势图，多寄存器对比
3. **阈值告警 WebSocket 推送**：温度/压力超限自动告警
4. **设备拓扑 SVG 图**：可视化设备布局与在线状态
5. **采集任务调度**：可调轮询间隔，设备启停控制
6. **严格的读写校验**：非法设备/地址/数量明确失败并说明原因，写入失败保留原值，批量读取单点失败不影响其它点位

## 启动
```bash
cd frontend && npm install && npm run dev
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8002
```

## 后端接口契约

### 读取（单个）
`GET /api/modbus/read/{device_id}/{address}/{count}`

- 成功 `200`：`{"status":"success","values":[...],"engineering_values":[...],"points":[...]}`
  - `values` 为 16 位原始寄存器值；`engineering_values`/`points[].value` 为按各寄存器 `scale` 换算后的工程量
- 失败返回 4xx/5xx，响应体统一为：
  `{"status":"failed","error":{"code":"错误码","message":"原因"}}`

### 批量读取
`POST /api/modbus/read/batch`，请求体 `{"points":[{"device_id":"dev1","address":0,"count":1}, ...]}`

- HTTP 始终 `200`，每个点位独立校验：`results[].status` 为 `success` 或 `failed`
- 顶层 `status`：全部成功 `success` / 全部失败 `failed` / 部分失败 `partial`，并给出 `succeeded`、`failed` 计数
- 某个点位失败不会影响其它点位继续读取

### 写入
`POST /api/modbus/write/{device_id}/{address}`，值通过查询参数 `?value=123` 或 JSON 体 `{"value": 123}` 传入。

- 成功 `200`：`{"status":"success","value":新值,"previous_value":旧值}`
- 仅当设备存在且在线、地址存在、寄存器可写、数值在合法范围内时才真正写入
- 任一校验失败都返回 4xx/5xx 且**不修改寄存器镜像**（读到的仍是原值）

### 错误码
| code | HTTP | 含义 |
| --- | --- | --- |
| `DEVICE_NOT_FOUND` | 404 | 设备不存在 |
| `DEVICE_OFFLINE` | 503 | 设备离线 |
| `ADDRESS_OUT_OF_RANGE` | 400 | 地址/读取范围超出该设备寄存器区间，或超出 0-65535 |
| `INVALID_ADDRESS` | 400 | 地址不是非负整数 |
| `COUNT_OUT_OF_RANGE` | 400 | 读取数量超过单次上限 125 |
| `INVALID_COUNT` | 400 | 读取数量不是 >=1 的整数 |
| `VALUE_OUT_OF_RANGE` | 400 | 写入值超出 0-65535 或该寄存器自身允许范围 |
| `INVALID_VALUE` | 400 | 写入值缺失或不是整数 |
| `REGISTER_NOT_WRITABLE` | 400 | 目标为只读/非保持寄存器 |
| `INVALID_REQUEST` | 422 | 请求参数类型/结构错误 |

## 测试
```bash
cd backend && python3 -m pytest tests/ -q
```
