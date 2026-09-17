import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { Device, Alarm, ModbusRegister, OpLog } from '../types'
import {
  readRegisters as apiRead,
  readBatch as apiReadBatch,
  writeRegister as apiWrite,
  ApiError,
  type BatchPointResult,
} from '../api/modbus'

export const useModbusStore = defineStore('modbus', () => {
  const devices = ref<Device[]>([])
  const alarms = ref<Alarm[]>([])
  const historyData = ref<Record<string, { time: number[]; values: number[] }>>({})
  const isPolling = ref(false)
  const pollInterval = ref(1000)
  const selectedDevice = ref<Device | null>(null)

  /** 下发/读取操作记录：成功与失败分别标记，失败保留原因 */
  const opLogs = ref<OpLog[]>([])
  let logSeq = 0
  function addLog(log: Omit<OpLog, 'id' | 'timestamp'>) {
    opLogs.value.unshift({ ...log, id: `op_${Date.now()}_${logSeq++}`, timestamp: Date.now() })
    if (opLogs.value.length > 100) opLogs.value.length = 100
  }

  const criticalAlarms = computed(() => alarms.value.filter(a => a.level === 'critical' && !a.acknowledged))
  const onlineDevices = computed(() => devices.value.filter(d => d.online))

  function initMockDevices() {
    devices.value = [
      {
        id: 'dev1', name: '温湿度传感器-A区', ip: '192.168.1.101', port: 502, slaveId: 1, online: true,
        registers: [
          { address: 0, name: '温度', type: 'holding', value: 25.6, unit: '°C', updatedAt: Date.now() },
          { address: 1, name: '湿度', type: 'holding', value: 62.3, unit: '%RH', updatedAt: Date.now() },
          { address: 2, name: '露点', type: 'holding', value: 17.8, unit: '°C', updatedAt: Date.now() },
        ]
      },
      {
        id: 'dev2', name: '压力变送器-B区', ip: '192.168.1.102', port: 502, slaveId: 2, online: true,
        registers: [
          { address: 0, name: '管道压力', type: 'holding', value: 3.45, unit: 'MPa', updatedAt: Date.now() },
          { address: 1, name: '差压', type: 'holding', value: 0.12, unit: 'kPa', updatedAt: Date.now() },
        ]
      },
      {
        id: 'dev3', name: '电机控制器-C区', ip: '192.168.1.103', port: 502, slaveId: 3, online: false,
        registers: [
          { address: 0, name: '转速', type: 'holding', value: 1480, unit: 'RPM', updatedAt: Date.now() },
          { address: 1, name: '电流', type: 'holding', value: 12.5, unit: 'A', updatedAt: Date.now() },
          { address: 2, name: '运行状态', type: 'coil', value: true, unit: '', updatedAt: Date.now() },
        ]
      },
      {
        id: 'dev4', name: '流量计-D区', ip: '192.168.1.104', port: 502, slaveId: 4, online: true,
        registers: [
          { address: 0, name: '瞬时流量', type: 'holding', value: 156.7, unit: 'L/min', updatedAt: Date.now() },
          { address: 1, name: '累计流量', type: 'holding', value: 98234, unit: 'L', updatedAt: Date.now() },
        ]
      },
    ]
    selectedDevice.value = devices.value[0]
  }

  function simulatePoll() {
    for (const dev of devices.value) {
      if (!dev.online) continue
      for (const reg of dev.registers) {
        if (typeof reg.value === 'number') {
          const noise = (Math.random() - 0.5) * reg.value * 0.02
          reg.value = Math.round((reg.value + noise) * 100) / 100
          reg.updatedAt = Date.now()
          const key = `${dev.id}_${reg.address}`
          if (!historyData.value[key]) historyData.value[key] = { time: [], values: [] }
          historyData.value[key].time.push(Date.now())
          historyData.value[key].values.push(reg.value)
          if (historyData.value[key].time.length > 100) {
            historyData.value[key].time.shift()
            historyData.value[key].values.shift()
          }
          // Check thresholds
          if (reg.name === '温度' && reg.value > 28) {
            alarms.value.unshift({
              id: `a_${Date.now()}`, deviceId: dev.id, register: reg.name,
              message: `${dev.name} ${reg.name}超限: ${reg.value}${reg.unit}`,
              level: reg.value > 30 ? 'critical' : 'warning',
              timestamp: Date.now(), acknowledged: false
            })
          }
        }
      }
    }
    if (alarms.value.length > 50) alarms.value = alarms.value.slice(0, 50)
  }

  function acknowledgeAlarm(id: string) {
    const a = alarms.value.find(a => a.id === id)
    if (a) a.acknowledged = true
  }

  function toggleDevice(id: string) {
    const d = devices.value.find(d => d.id === id)
    if (d) d.online = !d.online
  }

  /** 单寄存器/范围读取。无效目标、地址或超范围数量会抛出带原因的 ApiError。 */
  async function readRemote(deviceId: string, address: number, count: number) {
    try {
      const res = await apiRead(deviceId, address, count)
      addLog({
        kind: 'read', status: 'success', deviceId, address,
        detail: `地址 ${address} 数量 ${res.count}，值: [${res.values.join(', ')}]`,
      })
      return res
    } catch (err) {
      const e = err as ApiError
      addLog({ kind: 'read', status: 'failure', deviceId, address, errorCode: e.code, error: e.message })
      throw e
    }
  }

  /** 批量读取：后端逐点返回结果，单点失败不影响其它点位。 */
  async function readRemoteBatch(points: { device_id: string; address: number }[]) {
    try {
      const res = await apiReadBatch(points)
      for (const r of res.results) {
        addLog(r.success
          ? { kind: 'batch-read', status: 'success', deviceId: r.device_id, address: r.address, detail: `${r.name}=${r.value}${r.unit ?? ''}` }
          : { kind: 'batch-read', status: 'failure', deviceId: r.device_id, address: r.address, errorCode: r.error_code, error: r.error })
      }
      return res
    } catch (err) {
      // 整批被拒绝（空列表/超过点位上限等）
      const e = err as ApiError
      addLog({ kind: 'batch-read', status: 'failure', deviceId: points.map(p => p.device_id).join(',') || '-', errorCode: e.code, error: e.message })
      throw e
    }
  }

  /** 下发写值。失败时后端保留原值；仅成功才同步本地展示值。 */
  async function writeRemote(deviceId: string, address: number, value: number) {
    try {
      const res = await apiWrite(deviceId, address, value)
      addLog({
        kind: 'write', status: 'success', deviceId, address,
        detail: `${res.register_name}: ${res.old_value} → ${res.value}`,
      })
      syncWrittenValue(deviceId, address, res.value)
      return res
    } catch (err) {
      const e = err as ApiError
      addLog({ kind: 'write', status: 'failure', deviceId, address, errorCode: e.code, error: e.message })
      throw e
    }
  }

  /** 写入成功后把后端真实值同步到本地仪表盘（失败不调用，旧值保留）。 */
  function syncWrittenValue(deviceId: string, address: number, value: number) {
    const dev = devices.value.find(d => d.id === deviceId)
    const reg = dev?.registers.find(r => r.address === address)
    if (reg) {
      reg.value = value
      reg.updatedAt = Date.now()
    }
  }

  return {
    devices, alarms, historyData, isPolling, pollInterval, selectedDevice, opLogs,
    criticalAlarms, onlineDevices,
    initMockDevices, simulatePoll, acknowledgeAlarm, toggleDevice,
    readRemote, readRemoteBatch, writeRemote, syncWrittenValue,
  }
})
