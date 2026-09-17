import axios, { AxiosError } from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 10000 })

export interface ApiError {
  code: string
  message: string
}

export interface ReadPoint {
  address: number
  name: string
  unit: string
  writable: boolean
  raw_value: number
  value: number
}

export interface ReadResponse {
  status: 'success'
  device_id: string
  address: number
  count: number
  values: number[]
  engineering_values?: number[]
  points?: ReadPoint[]
}

export interface WriteResponse {
  status: 'success'
  device_id: string
  address: number
  value: number
  previous_value: number
}

export interface BatchPointResult {
  index?: number
  status: 'success' | 'failed'
  device_id?: string
  address?: number
  count?: number
  values?: number[]
  points?: ReadPoint[]
  error?: ApiError
}

export interface BatchReadResponse {
  status: 'success' | 'partial' | 'failed'
  total: number
  succeeded: number
  failed: number
  results: BatchPointResult[]
}

function toApiError(err: unknown): ApiError {
  const ax = err as AxiosError<{ error?: ApiError }>
  return (
    ax.response?.data?.error ?? {
      code: 'NETWORK_ERROR',
      message: '无法连接采集服务，请检查后端是否启动',
    }
  )
}

export const modbusApi = {
  async read(deviceId: string, address: number, count = 1): Promise<ReadResponse> {
    const { data } = await http.get<ReadResponse>(
      `/modbus/read/${deviceId}/${address}/${count}`,
    )
    return data
  },

  async batchRead(
    points: { device_id: string; address: number; count?: number }[],
  ): Promise<BatchReadResponse> {
    const { data } = await http.post<BatchReadResponse>('/modbus/read/batch', { points })
    return data
  },

  async write(deviceId: string, address: number, value: number): Promise<WriteResponse> {
    const { data } = await http.post<WriteResponse>(
      `/modbus/write/${deviceId}/${address}`,
      { value },
    )
    return data
  },

  /** Normalise any thrown error into a structured {code,message}. */
  asError(err: unknown): ApiError {
    return toApiError(err)
  },
}
