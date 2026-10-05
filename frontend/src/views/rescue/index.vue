<template>
  <section class="page" data-module="rescue">
    <header class="page-head">
      <div>
        <h2>应急救援管理</h2>
        <p class="page-desc">合格判定只有一份口径：保有数量为零或下次检查日过期即不合格，两条同时命中以过期为准；列表与详情读同一份结论。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出应急救援清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statsCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="item.tone">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>装备编号</span>
        <input v-model="keyword" placeholder="按装备编号检索" />
      </label>
      <label class="filter-item">
        <span>判定</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <button v-if="column === '装备编号'" class="link" type="button" @click="openDetail(row)">{{ row[column] }}</button>
            <span
              v-else-if="column === '判定'"
              :class="['judgement-tag', row.是否合格 === '合格' ? 'ok' : 'bad']"
            >{{ row[column] }}</span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="recordInspection(row)">登记检查</button>
            <button class="link" type="button" @click="runAction('补充装备', row)">补充装备</button>
            <button class="link" type="button" @click="runAction('申请报废', row)">申请报废</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无应急救援数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条救援装备记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal-card">
        <header class="modal-head">
          <h3>装备详情：{{ detail['装备编号'] }}</h3>
          <button class="link" type="button" @click="detail = null">关闭</button>
        </header>
        <dl class="detail-list">
          <div v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>{{ detail[field] ?? '—' }}</dd>
          </div>
        </dl>
        <section class="history-box">
          <h4>判定历史（旧结论按当时口径保留，只追加不改写）</h4>
          <ul>
            <li v-for="(item, index) in detail['判定历史'] ?? []" :key="index">
              {{ item['时间'] }}｜{{ item['触发'] }}｜结论：{{ item['结论'] }}｜{{ item['依据'] }}（{{ item['口径版本'] }}）
            </li>
          </ul>
        </section>
        <p class="consistency-note">
          列表判定：<strong :class="detail.是否合格 === '合格' ? 'ok' : 'bad'">{{ detail['判定'] }}</strong>
          （{{ detail['是否合格'] }}，{{ detail['判定依据'] }}）——与详情同一份 evaluate 结果。
        </p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | string[] | null | Record<string, unknown>>

const ENDPOINT = '/api/rescue'
const columns = ["装备编号", "装备名称", "装备类别", "存放地点", "保有数量", "上次检查", "下次检查日", "判定", "判定依据", "待检"]
const statuses = ["合格可用", "已过期", "已报废"]
const detailFields = ["装备编号", "装备名称", "装备类别", "存放地点", "保有数量", "进场时间", "上次检查", "下次检查日", "判定", "是否合格", "判定依据", "命中判定", "判定口径", "判定基准日", "待检"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const detail = ref<Row | null>(null)
const stats = ref<Record<string, number>>({ 合格: 0, 已过期: 0, 已报废: 0, 待检: 0 })

const statsCards = computed(() => [
  { label: '合格装备', value: stats.value['合格'] ?? 0, tone: 'ok' },
  { label: '过期装备', value: stats.value['已过期'] ?? 0, tone: 'bad' },
  { label: '已报废', value: stats.value['已报废'] ?? 0, tone: 'bad' },
  { label: '待检', value: stats.value['待检'] ?? 0, tone: '' },
])

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('装备详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '装备详情读取失败'
  }
}

async function recordInspection(row: Row) {
  const lastCheck = window.prompt('上次检查日期（YYYY-MM-DD）', String(row['上次检查'] ?? ''))
  if (lastCheck === null) {
    return
  }
  const nextCheck = window.prompt('下次检查日（YYYY-MM-DD，不得早于上次检查）', String(row['下次检查日'] ?? ''))
  if (nextCheck === null) {
    return
  }
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/inspections`, {
      method: 'POST',
      body: JSON.stringify({ 上次检查: lastCheck, 下次检查日: nextCheck }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '检查记录未保存')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '检查记录保存失败'
  }
}

async function runAction(action: string, row: Row, body: Record<string, unknown> = {}) {
  errorMessage.value = ''
  if (action === '补充装备') {
    const input = window.prompt('补充数量', '1')
    if (input === null) {
      return
    }
    body = { 补充数量: input }
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action, ...body }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '应急救援动作未生效')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '应急救援操作失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (response.ok) {
      stats.value = await response.json()
    }
  } catch {
    // 统计失败不阻塞列表
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) {
    query.set('keyword', keyword.value)
  }
  if (statusFilter.value) {
    query.set('status', statusFilter.value)
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('救援装备列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await reloadStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '应急救援列表读取失败'
  }
}

onMounted(reload)
</script>
