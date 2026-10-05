<template>
  <section class="page" data-module="emergencydrill">
    <header class="page-head">
      <div>
        <h2>应急演练管理</h2>
        <p class="page-desc">演练装备清单的合格判定与救援装备台账同源：装备报废、归零或检查过期，演练清单上的结论同步变化，不另行下结论。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记演练记录</button>
        <button class="btn" type="button" @click="exportRows">导出应急演练清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>装备判定明细</th>
          <th>装备判定汇总</th>
          <th>参演放行</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <template v-if="equipmentItems(row).length">
              <div v-for="item in equipmentItems(row)" :key="item['装备编号']">
                {{ item['装备编号'] }}：{{ item['判定状态'] }}
              </div>
            </template>
            <span v-else>—</span>
          </td>
          <td>{{ typeof row['装备判定汇总'] === 'string' ? row['装备判定汇总'] : '—' }}</td>
          <td>
            <span :class="isAllQualified(row) ? 'verdict-pass' : 'verdict-fail'">
              {{ isAllQualified(row) ? '可参演' : '禁止参演' }}
            </span>
          </td>
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
          <td :colspan="columns.length + 4" class="empty-state">暂无应急演练数据，可先登记演练记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条应急演练记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null | EquipmentVerdict[]>

interface EquipmentVerdict {
  '装备编号': string
  '判定结果': string
  '判定状态': string
}

const ENDPOINT = '/api/emergencydrill'
const columns = ["演练编号", "演练主题", "演练区域", "参演人数", "演练日期", "装备清单", "演练评估", "改进措施", "演练状态"]
const actions = ["组织演练", "完成演练", "复盘总结"]
const statuses = ["待组织", "已组织", "已完成", "已复盘"]
const stats = [{"label": "待组织演练", "value": 0}, {"label": "已完成演练", "value": 0}, {"label": "已复盘演练", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function equipmentItems(row: Row): EquipmentVerdict[] {
  const items = row['装备判定明细']
  return Array.isArray(items) ? (items as EquipmentVerdict[]) : []
}

function isAllQualified(row: Row): boolean {
  return row['装备全部合格'] === true
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '演练记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('应急演练动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '应急演练操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('演练记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '应急演练列表读取失败'
  }
}

onMounted(reload)
</script>
