import axios from 'axios'

/** 后端统一的失败响应体（HTTP 4xx/5xx 与成功响应明确区分） */
export interface ApiErrorBody {
  success: false
  error_code: string
  error: string
  details?: Record<string, any>
}

export interface ReadResponse {
  success: true
  device_id: string
  address: number
  count: number
  values: number[]
}

export interface WriteResponse {
  success: true
  device_id: string
  address: number
  register_name: string
  old_value: number
  value: number
}

export interface BatchPointResult {
  index: number
  device_id: string
  address: number
  success: boolean
  name?: string
  value?: number
  unit?: string
  error_code?: string
  error?: string
}

export interface BatchReadResponse {
  success: boolean
  total: number
  success_count: number
  failure_count: number
  results: BatchPointResult[]
}

export class ApiError extends Error {
  code: string
  details?: Record<string, any>
  constructor(body: ApiErrorBody) {
    super(body.error)
    this.code = body.error_code
    this.details = body.details
  }
}

const http = axios.create({ baseURL: '/api', timeout: 10000 })

function toApiError(err: unknown): ApiError {
  if (axios.isAxiosError(err) && err.response?.data && err.response.data.success === false) {
    return new ApiError(err.response.data as ApiErrorBody)
  }
  if (axios.isAxiosError(err)) {
    return new ApiError({
      success: false,
      error_code: 'NETWORK_ERROR',
      error: `网络请求失败: ${err.message}`,
    })
  }
  return new ApiError({ success: false, error_code: 'UNKNOWN_ERROR', error: String(err) })
}

export async function readRegisters(deviceId: string, address: number, count: number): Promise<ReadResponse> {
  try {
    const res = await http.get<ReadResponse>(`/modbus/read/${deviceId}/${address}/${count}`)
    return res.data
  } catch (err) {
    throw toApiError(err)
  }
}

export async function readBatch(points: { device_id: string; address: number }[]): Promise<BatchReadResponse> {
  try {
    const res = await http.post<BatchReadResponse>('/modbus/read/batch', { points })
    return res.data
  } catch (err) {
    throw toApiError(err)
  }
}

export async function writeRegister(deviceId: string, address: number, value: number | boolean): Promise<WriteResponse> {
  try {
    const res = await http.post<WriteResponse>(`/modbus/write/${deviceId}/${address}`, {
      value: typeof value === 'boolean' ? Number(value) : value,
    })
    return res.data
  } catch (err) {
    throw toApiError(err)
  }
}
