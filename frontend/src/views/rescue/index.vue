<template>
  <section class="page" data-module="rescue">
    <header class="page-head">
      <div>
        <h2>应急救援管理</h2>
        <p class="page-desc">保有数量与检查日按统一口径合并判定：数量归零或检查日过期即不合格，同时命中以过期为准；列表、详情、演练清单、入井名单同读这一份结论。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记救援装备</button>
        <button class="btn" type="button" @click="exportRows">导出应急救援清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>装备编号</span>
        <input v-model="keyword" placeholder="按装备编号检索" />
      </label>
      <label class="filter-item">
        <span>判定状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="s in verdictStatuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>判定依据</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '装备状态'">
              <button class="link" type="button" @click="showDetail(row)">{{ row['判定状态'] ?? '—' }}</button>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td>{{ row['判定说明'] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无应急救援数据，可先登记救援装备</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条应急救援记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal-card">
        <header class="modal-head">
          <h3>{{ detail.装备编号 }} · 判定详情</h3>
          <button class="link" type="button" @click="detail = null">关闭</button>
        </header>
        <dl class="detail-grid">
          <template v-for="item in detailRows" :key="item.label">
            <dt>{{ item.label }}</dt>
            <dd>{{ item.value }}</dd>
          </template>
        </dl>
        <h4>判定历史（旧结论按当时口径保留）</h4>
        <table class="data-table">
          <thead>
            <tr><th>时间</th><th>场景</th><th>口径版本</th><th>判定</th><th>判定状态</th></tr>
          </thead>
          <tbody>
            <tr v-for="(h, i) in (detail['判定历史'] ?? [])" :key="i">
              <td>{{ h['时间'] }}</td>
              <td>{{ h['场景'] }}</td>
              <td>{{ h['口径版本'] }}</td>
              <td>{{ h['判定'] }}</td>
              <td>{{ h['判定状态'] }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | string[] | null>
type HistoryItem = Record<string, string>

const ENDPOINT = '/api/rescue'
const columns = ["装备编号", "装备名称", "装备类别", "存放地点", "保有数量", "上次检查", "下次检查日", "装备状态"]
const actions = ["登记检查", "补充装备", "申请报废"]
const verdictStatuses = ["合格可用", "已过期", "无保有量", "已报废"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const counts = ref<Record<string, number>>({})
const detail = ref<(Row & { '判定历史'?: HistoryItem[] }) | null>(null)

const statCards = computed(() => [
  { label: "合格装备", value: counts.value["合格装备"] ?? 0 },
  { label: "待检提醒", value: counts.value["待检提醒"] ?? 0 },
  { label: "过期装备", value: counts.value["过期装备"] ?? 0 },
  { label: "无保有量", value: counts.value["无保有量"] ?? 0 },
  { label: "已报废", value: counts.value["已报废"] ?? 0 },
])

const detailRows = computed(() => {
  const d = detail.value
  if (!d) return []
  return [
    { label: '判定结果', value: String(d['判定结果'] ?? '—') },
    { label: '判定状态', value: String(d['判定状态'] ?? '—') },
    { label: '命中规则', value: ((d['命中规则'] as string[] | undefined) ?? []).join('、') || '无' },
    { label: '生效规则', value: String(d['生效规则'] || '无（合格）') },
    { label: '判定说明', value: String(d['判定说明'] ?? '—') },
    { label: '判定口径', value: String(d['判定口径版本'] ?? '—') },
    { label: '是否待检', value: d['待检'] ? '是' : '否' },
  ]
})

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '救援装备登记入口尚未接入审批流'
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (response.ok) {
      counts.value = await response.json()
    }
  } catch {
    // 统计失败不阻塞列表
  }
}

function askActionParams(action: string, row: Row): Record<string, string | number> | null {
  if (action === '登记检查') {
    const last = window.prompt('本次检查日期（YYYY-MM-DD），不得早于上次检查')
    if (!last) return null
    const next = window.prompt('下次检查日（YYYY-MM-DD），不得早于本次检查')
    if (!next) return null
    return { action, '上次检查': last, '下次检查日': next }
  }
  if (action === '补充装备') {
    const qty = window.prompt('补充后的保有数量（必须大于 0）', String(row['保有数量'] ?? 1))
    if (qty === null) return null
    return { action, '保有数量': Number(qty) }
  }
  return { action }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  const values = askActionParams(action, row)
  if (!values) return
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '应急救援动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '应急救援操作失败'
  }
}

async function showDetail(row: Row) {
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

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('救援装备列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await loadStats()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '应急救援列表读取失败'
  }
}

onMounted(reload)
</script>
