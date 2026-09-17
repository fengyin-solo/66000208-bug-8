<template>
  <div class="bg-gray-900 rounded-xl p-3 flex flex-col gap-2">
    <h3 class="text-sm text-gray-400">寄存器下发</h3>

    <select v-model="deviceId" class="bg-gray-800 text-xs rounded p-1.5">
      <option v-for="d in store.devices" :key="d.id" :value="d.id">
        {{ d.name }}{{ d.online ? '' : ' (离线)' }}
      </option>
    </select>

    <select v-if="writableRegisters.length" v-model.number="address" class="bg-gray-800 text-xs rounded p-1.5">
      <option v-for="r in writableRegisters" :key="r.address" :value="r.address">
        地址 {{ r.address }} · {{ r.name }} (当前: {{ displayCurrent(r) }}{{ r.unit }})
      </option>
    </select>
    <div v-else class="text-xs text-red-400 bg-red-900/30 rounded p-1.5">
      该设备没有可写寄存器，下发将被拒绝
    </div>

    <div v-if="selectedRegister" class="text-[11px] text-gray-500">
      允许范围: {{ selectedRegister.minValue ?? 0 }} ~ {{ selectedRegister.maxValue ?? 65535 }}
      <span class="text-gray-600">（整数，16 位原始寄存器值）</span>
    </div>

    <input
      v-model.number="rawValue"
      type="number"
      :disabled="!writableRegisters.length || !deviceOnline"
      class="bg-gray-800 text-xs rounded p-1.5 disabled:opacity-50"
      placeholder="输入要写入的整数值"
    />

    <button
      @click="submitWrite"
      :disabled="writing || !writableRegisters.length || !deviceOnline"
      class="bg-orange-700 text-xs py-1.5 rounded hover:bg-orange-600 disabled:opacity-50"
    >
      {{ writing ? '下发中...' : '下发写入' }}
    </button>

    <!-- Success vs failure are visually and structurally distinct -->
    <div v-if="result" class="rounded p-2 text-xs" :class="result.kind === 'success' ? 'bg-green-900/40 border border-green-700' : 'bg-red-900/40 border border-red-700'">
      <div class="font-bold" :class="result.kind === 'success' ? 'text-green-400' : 'text-red-400'">
        {{ result.kind === 'success' ? '✓ 写入成功' : '✗ 写入失败' }}
      </div>
      <div class="mt-1" :class="result.kind === 'success' ? 'text-green-200' : 'text-red-200'">
        {{ result.message }}
      </div>
    </div>

    <div class="border-t border-gray-800 pt-2 mt-1">
      <button @click="runBatchDemo" :disabled="batchLoading"
        class="w-full bg-gray-700 text-[11px] py-1 rounded hover:bg-gray-600 disabled:opacity-50">
        {{ batchLoading ? '读取中...' : '批量读取诊断（含非法点位）' }}
      </button>
      <div v-if="batchSummary" class="text-[11px] mt-1 text-gray-400">
        成功 {{ batchSummary.succeeded }} / 失败 {{ batchSummary.failed }}
      </div>
      <div
        v-for="row in batchRows"
        :key="row.key"
        class="text-[11px] mt-1 rounded px-1.5 py-1"
        :class="row.status === 'success' ? 'bg-green-900/30 text-green-300' : 'bg-red-900/30 text-red-300'"
      >
        {{ row.label }}：{{ row.status === 'success'
          ? `成功，值=${row.values}`
          : `失败 [${row.errorCode}] ${row.errorMessage}` }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useModbusStore } from '../store/modbus'
import { modbusApi, type BatchPointResult } from '../api/modbus'

const store = useModbusStore()
const { selectedDevice } = storeToRefs(store)

const deviceId = ref(selectedDevice.value?.id ?? 'dev1')
const address = ref(0)
const rawValue = ref<number | null>(null)
const writing = ref(false)
const result = ref<{ kind: 'success' | 'failed'; message: string } | null>(null)
const batchLoading = ref(false)
const batchRows = ref<Array<{
  key: string
  label: string
  status: 'success' | 'failed'
  values?: number[]
  errorCode?: string
  errorMessage?: string
}>>([])
const batchSummary = ref<{ succeeded: number; failed: number } | null>(null)

watch(deviceId, () => {
  address.value = writableRegisters.value[0]?.address ?? 0
  result.value = null
})

const device = computed(() => store.devices.find(d => d.id === deviceId.value))
const deviceOnline = computed(() => !!device.value?.online)
const writableRegisters = computed(() =>
  (device.value?.registers ?? []).filter(r => r.writable),
)
const selectedRegister = computed(() =>
  writableRegisters.value.find(r => r.address === address.value),
)

function displayCurrent(reg: { value: number | boolean }) {
  return typeof reg.value === 'number' ? reg.value : reg.value ? 'ON' : 'OFF'
}

async function submitWrite() {
  result.value = null
  if (selectedRegister.value == null) {
    result.value = { kind: 'failed', message: '目标寄存器不可写或不存在，已拒绝下发' }
    return
  }
  if (rawValue.value === null || !Number.isInteger(rawValue.value)) {
    result.value = { kind: 'failed', message: '写入值必须是整数' }
    return
  }
  const min = selectedRegister.value.minValue ?? 0
  const max = selectedRegister.value.maxValue ?? 65535
  if (rawValue.value < min || rawValue.value > max) {
    result.value = {
      kind: 'failed',
      message: `写入值超出允许范围 (${min}~${max}): ${rawValue.value}，未下发`,
    }
    return
  }

  writing.value = true
  try {
    const resp = await modbusApi.write(deviceId.value, address.value, rawValue.value)
    // Confirm via a fresh read so the dashboard shows the real device value.
    const readback = await modbusApi.read(deviceId.value, address.value, 1)
    const point = readback.points?.[0]
    const engineering = point?.value
    store.syncRegisterValue(
      deviceId.value,
      address.value,
      engineering ?? resp.value,
    )
    result.value = {
      kind: 'success',
      message: `原始值 ${resp.previous_value} → ${resp.value}` +
        (engineering != null ? `，工程量 ${engineering}${point?.unit ?? ''}` : '') +
        '，已回读确认',
    }
  } catch (err) {
    const apiError = modbusApi.asError(err)
    // No local state mutation: the panel/dashboard retain the previous value.
    result.value = {
      kind: 'failed',
      message: `[${apiError.code}] ${apiError.message}（原值保留不变）`,
    }
  } finally {
    writing.value = false
  }
}

async function runBatchDemo() {
  batchLoading.value = true
  batchSummary.value = null
  batchRows.value = []
  // One valid point plus several deliberately invalid ones, to show that a
  // failed point never blocks the others.
  const points = [
    { device_id: deviceId.value, address: 0, count: 1 },
    { device_id: 'dev-not-exist', address: 0, count: 1 },
    { device_id: deviceId.value, address: 0, count: 99999 },
    { device_id: deviceId.value, address: 999999, count: 1 },
  ]
  const labels = [
    `${deviceId.value}@0`,
    'dev-not-exist@0',
    `${deviceId.value}@0 count=99999`,
    `${deviceId.value}@999999`,
  ]
  try {
    const resp = await modbusApi.batchRead(points)
    batchSummary.value = { succeeded: resp.succeeded, failed: resp.failed }
    batchRows.value = resp.results.map((r: BatchPointResult, i: number) => ({
      key: `${i}`,
      label: labels[i],
      status: r.status,
      values: r.values,
      errorCode: r.error?.code,
      errorMessage: r.error?.message,
    }))
  } catch (err) {
    const apiError = modbusApi.asError(err)
    batchRows.value = [{
      key: 'net', label: '请求', status: 'failed',
      errorCode: apiError.code, errorMessage: apiError.message,
    }]
  } finally {
    batchLoading.value = false
  }
}
</script>
