<template>
  <section class="page" data-module="shift">
    <header class="page-head">
      <div>
        <h2>入井管理</h2>
        <p class="page-desc">入井携带设备的合格判定与救援装备台账同源：装备报废、归零或检查过期，入井名单同步标记为不合格，未复核合格不得放行入井。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记入井记录</button>
        <button class="btn" type="button" @click="exportRows">导出入井管理清单</button>
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
          <th>携带装备判定</th>
          <th>装备判定汇总</th>
          <th>入井放行</th>
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
              {{ isAllQualified(row) ? '放行' : '禁止入井' }}
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
          <td :colspan="columns.length + 4" class="empty-state">暂无入井管理数据，可先登记入井记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条入井管理记录</span>
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

const ENDPOINT = '/api/shift'
const columns = ["记录编号", "入井人员", "所属班组", "入井时间", "升井时间", "携带设备", "出勤区域", "入井状态"]
const actions = ["登记入井", "登记升井", "超时联系"]
const statuses = ["入井中", "已升井", "超时未升", "已联系"]
const stats = [{"label": "入井中人数", "value": 0}, {"label": "已升井人数", "value": 0}, {"label": "超时人数", "value": 0}]

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
  errorMessage.value = '入井记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('入井管理动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '入井管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('入井记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '入井管理列表读取失败'
  }
}

onMounted(reload)
</script>
