<template>
  <div class="bg-gray-900 rounded-xl p-3">
    <h3 class="text-sm text-gray-400 mb-2">读数 / 下发面板</h3>

    <div class="grid grid-cols-3 gap-3">
      <!-- 单读 / 范围读 -->
      <div class="bg-gray-800 rounded-lg p-2">
        <div class="text-xs text-gray-300 mb-2 font-semibold">读取寄存器</div>
        <label class="text-[11px] text-gray-500">设备</label>
        <select v-model="readDevice" class="w-full bg-gray-900 text-xs rounded px-1.5 py-1 mb-1.5 text-gray-200">
          <option v-for="d in store.devices" :key="d.id" :value="d.id">{{ d.name }}{{ d.online ? '' : '（离线）' }}</option>
        </select>
        <div class="flex gap-1.5">
          <div class="flex-1">
            <label class="text-[11px] text-gray-500">起始地址</label>
            <input v-model.number="readAddress" type="number" min="0" max="65535"
              class="w-full bg-gray-900 text-xs rounded px-1.5 py-1 text-gray-200" />
          </div>
          <div class="flex-1">
            <label class="text-[11px] text-gray-500">数量(1-125)</label>
            <input v-model.number="readCount" type="number" min="1" max="125"
              class="w-full bg-gray-900 text-xs rounded px-1.5 py-1 text-gray-200" />
          </div>
        </div>
        <button @click="doRead" :disabled="busy"
          class="mt-2 w-full bg-cyan-700 py-1 rounded text-xs hover:bg-cyan-600 disabled:opacity-50">
          读取
        </button>
      </div>

      <!-- 批量读 -->
      <div class="bg-gray-800 rounded-lg p-2">
        <div class="text-xs text-gray-300 mb-2 font-semibold">
          批量点位读取
          <span class="text-gray-500 font-normal">（每行 设备ID:地址，最多100点）</span>
        </div>
        <textarea v-model="batchInput" rows="3" placeholder="dev1:0&#10;dev_x:5&#10;dev1:77"
          class="w-full bg-gray-900 text-xs rounded px-1.5 py-1 text-gray-200 font-mono"></textarea>
        <button @click="doBatchRead" :disabled="busy"
          class="mt-2 w-full bg-cyan-700 py-1 rounded text-xs hover:bg-cyan-600 disabled:opacity-50">
          批量读取（失败不影响其它点）
        </button>
      </div>

      <!-- 写值下发 -->
      <div class="bg-gray-800 rounded-lg p-2">
        <div class="text-xs text-gray-300 mb-2 font-semibold">写入下发</div>
        <label class="text-[11px] text-gray-500">设备</label>
        <select v-model="writeDevice" class="w-full bg-gray-900 text-xs rounded px-1.5 py-1 mb-1.5 text-gray-200">
          <option v-for="d in store.devices" :key="d.id" :value="d.id">{{ d.name }}{{ d.online ? '' : '（离线）' }}</option>
        </select>
        <div class="flex gap-1.5">
          <div class="flex-1">
            <label class="text-[11px] text-gray-500">地址</label>
            <input v-model.number="writeAddress" type="number" min="0" max="65535"
              class="w-full bg-gray-900 text-xs rounded px-1.5 py-1 text-gray-200" />
          </div>
          <div class="flex-1">
            <label class="text-[11px] text-gray-500">值(uint16 / 线圈0,1)</label>
            <input v-model.number="writeValue" type="number"
              class="w-full bg-gray-900 text-xs rounded px-1.5 py-1 text-gray-200" />
          </div>
        </div>
        <button @click="doWrite" :disabled="busy"
          class="mt-2 w-full bg-orange-700 py-1 rounded text-xs hover:bg-orange-600 disabled:opacity-50">
          下发写入
        </button>
      </div>
    </div>

    <!-- 本次操作结果 -->
    <div v-if="lastResult" class="mt-2 rounded p-2 text-xs"
      :class="lastResult.ok ? 'bg-green-900/40 border border-green-700' : 'bg-red-900/40 border border-red-700'">
      <div class="font-semibold" :class="lastResult.ok ? 'text-green-400' : 'text-red-400'">
        {{ lastResult.ok ? '✓ 成功' : `✗ 失败 ${lastResult.errorCode ? '[' + lastResult.errorCode + ']' : ''}` }}
      </div>
      <div v-if="lastResult.ok" class="text-green-200 mt-0.5 break-all">{{ lastResult.text }}</div>
      <div v-else class="text-red-200 mt-0.5 break-all">{{ lastResult.text }}</div>

      <!-- 批量读逐点结果 -->
      <table v-if="batchResults.length" class="w-full mt-2 text-[11px]">
        <thead>
          <tr class="text-gray-400 text-left">
            <th class="py-0.5">#</th><th class="py-0.5">设备</th><th class="py-0.5">地址</th><th class="py-0.5">结果</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in batchResults" :key="r.index" :class="r.success ? 'text-green-300' : 'text-red-300'">
            <td>{{ r.index + 1 }}</td>
            <td>{{ r.device_id }}</td>
            <td>{{ r.address }}</td>
            <td>
              <span v-if="r.success">✓ {{ r.name }} = {{ r.value }}{{ r.unit }}</span>
              <span v-else>✗ [{{ r.error_code }}] {{ r.error }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useModbusStore } from '../store/modbus'
import { ApiError, type BatchPointResult } from '../api/modbus'

const store = useModbusStore()

const readDevice = ref('dev1')
const readAddress = ref(0)
const readCount = ref(1)
const batchInput = ref('dev1:0\ndev2:0\ndev_x:0\ndev1:77\ndev3:0')
const writeDevice = ref('dev1')
const writeAddress = ref(10)
const writeValue = ref(1000)

const busy = ref(false)
const lastResult = ref<{ ok: boolean; text: string; errorCode?: string } | null>(null)
const batchResults = ref<BatchPointResult[]>([])

async function run(action: () => Promise<void>) {
  busy.value = true
  batchResults.value = []
  try {
    await action()
  } finally {
    busy.value = false
  }
}

async function doRead() {
  await run(async () => {
    try {
      const res = await store.readRemote(readDevice.value, readAddress.value, readCount.value)
      lastResult.value = { ok: true, text: `读到 ${res.count} 个寄存器：[${res.values.join(', ')}]` }
    } catch (err) {
      const e = err as ApiError
      lastResult.value = { ok: false, errorCode: e.code, text: e.message }
    }
  })
}

function parseBatch(): { device_id: string; address: number }[] {
  return batchInput.value
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => {
      const [deviceId, addr] = line.split(':').map(s => s.trim())
      return { device_id: deviceId, address: Number(addr) }
    })
}

async function doBatchRead() {
  await run(async () => {
    const points = parseBatch()
    try {
      const res = await store.readRemoteBatch(points)
      batchResults.value = res.results
      lastResult.value = res.failure_count === 0
        ? { ok: true, text: `全部成功：${res.success_count}/${res.total} 个点位` }
        : {
            ok: false,
            errorCode: 'PARTIAL_FAILURE',
            text: `${res.success_count} 个点位读取成功，${res.failure_count} 个点位失败（失败点位未影响其它点位读取）`,
          }
    } catch (err) {
      const e = err as ApiError
      lastResult.value = { ok: false, errorCode: e.code, text: e.message }
    }
  })
}

async function doWrite() {
  await run(async () => {
    try {
      const res = await store.writeRemote(writeDevice.value, writeAddress.value, writeValue.value)
      lastResult.value = {
        ok: true,
        text: `写入成功：${res.register_name}（地址 ${res.address}）${res.old_value} → ${res.value}，再次读取即为新值`,
      }
    } catch (err) {
      const e = err as ApiError
      lastResult.value = { ok: false, errorCode: e.code, text: `写入失败，原值已保留。原因：${e.message}` }
    }
  })
}
</script>
