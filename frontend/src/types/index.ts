export interface ModbusRegister {
  address: number
  name: string
  type: 'coil' | 'discrete' | 'holding' | 'input'
  value: number | boolean
  unit: string
  updatedAt: number
}

export interface Device {
  id: string
  name: string
  ip: string
  port: number
  slaveId: number
  online: boolean
  registers: ModbusRegister[]
}

export interface Alarm {
  id: string
  deviceId: string
  register: string
  message: string
  level: 'info' | 'warning' | 'critical'
  timestamp: number
  acknowledged: boolean
}

export type OpKind = 'read' | 'write' | 'batch-read'
export type OpStatus = 'success' | 'failure'

export interface OpLog {
  id: string
  kind: OpKind
  deviceId: string
  address?: number
  /** 成功时的值描述；失败时为空 */
  detail?: string
  /** 失败原因（成功时为空），失败与成功据此可分辨 */
  errorCode?: string
  error?: string
  status: OpStatus
  timestamp: number
}
