<template>
  <section class="page" data-module="metmast">
    <header class="page-head">
      <div>
        <h2>测风塔管理</h2>
        <p class="page-desc">
          状态只能沿「数据缺失待复核 → 复核确认停用 → 复测恢复」依次流转，不允许跳级；
          停用期间不允许提交校验，恢复使用须登记复测结论与恢复时间。
          停用后塔架高度、测风层数仍可查看，数据完整率按停用前后的采集时段分开统计。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记测风塔</button>
        <button class="btn" type="button" @click="exportRows">导出测风塔清单</button>
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
        <span>塔架编号</span>
        <input v-model="keyword" placeholder="按塔架编号检索" />
      </label>
      <label class="filter-item">
        <span>测风状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>塔架编号</th>
          <th>所在场站</th>
          <th>塔架高度</th>
          <th>测风层数</th>
          <th>风速仪型号</th>
          <th>上次校验日</th>
          <th>数据完整率（分采集时段）</th>
          <th>状态</th>
          <th>最近操作</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-stopped': row.status === STATUS_STOPPED }">
          <td>{{ row['塔架编号'] ?? '—' }}</td>
          <td>{{ row['所在场站'] ?? '—' }}</td>
          <td>{{ row['塔架高度'] ?? '—' }}</td>
          <td>{{ row['测风层数'] ?? '—' }}</td>
          <td>{{ row['风速仪型号'] ?? '—' }}</td>
          <td>{{ row['上次校验日'] ?? '—' }}</td>
          <td class="rate-cell" :title="rateTitle(row)">{{ rateText(row) }}</td>
          <td><span class="status-tag" :class="statusClass(row.status)">{{ row.status }}</span></td>
          <td class="op-cell">{{ opText(row) }}</td>
          <td class="row-actions">
            <template v-for="action in availableActions(row.status)" :key="action">
              <button
                v-if="needsForm(action)"
                class="link"
                type="button"
                @click="openForm(action, row)"
              >
                {{ action }}
              </button>
              <button
                v-else
                class="link"
                type="button"
                @click="runDirectAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <button
              v-if="row.status === STATUS_STOPPED"
              class="link link-disabled"
              type="button"
              disabled
              title="停用期间不允许提交校验，请先完成复测恢复"
            >
              提交校验
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="10" class="empty-state">暂无测风塔数据，可先登记测风塔</td>
        </tr>
      </tbody>
    </table>

    <p v-if="stoppedCount" class="table-hint">
      已停用的 {{ stoppedCount }} 座测风塔，塔架高度与测风层数仍可查看；停用前完整率已按当时采集口径封账。
    </p>

    <footer class="page-foot">
      <span>共 {{ total }} 条测风塔记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="form.action" class="modal-mask" @click.self="closeForm">
      <div class="modal-box">
        <h3 class="modal-title">{{ form.action }} · {{ form.row ? form.row['塔架编号'] : '' }}</h3>
        <form @submit.prevent="submitForm">
          <label v-for="field in formFields" :key="field.name" class="modal-field">
            <span>{{ field.label }}<em v-if="field.required">*</em></span>
            <textarea
              v-if="field.type === 'textarea'"
              v-model="form.values[field.name]"
              :placeholder="field.placeholder"
              rows="2"
            ></textarea>
            <input
              v-else
              v-model="form.values[field.name]"
              :type="field.type || 'text'"
              :placeholder="field.placeholder"
            />
          </label>
          <p v-if="formError" class="error-text">{{ formError }}</p>
          <div class="modal-actions">
            <button class="btn primary" type="submit">确认{{ form.action }}</button>
            <button class="btn ghost" type="button" @click="closeForm">取消</button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type LedgerSegment = {
  label: string
  采集开始: string | null
  采集结束: string | null
  完整率: number | null
  采集口径: string
}
type OpRecord = { 动作: string; 时间: string; 说明: string } | null

const ENDPOINT = '/api/metmast'
const STATUS_STOPPED = '复核确认停用'
const statuses = ['待校验', '数据正常', '数据缺失待复核', '复核确认停用', '复测恢复']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const summary = ref<Record<string, number>>({})

const statCards = computed(() => [
  { label: '在运测风塔', value: summary.value['在运测风塔'] ?? 0 },
  { label: '数据缺失待复核', value: summary.value['数据缺失待复核'] ?? 0 },
  { label: '复核确认停用', value: summary.value['复核确认停用'] ?? 0 },
  { label: '待校验', value: summary.value['待校验'] ?? 0 },
])

const stoppedCount = computed(() => rows.value.filter((row) => row.status === STATUS_STOPPED).length)

// 每个状态只暴露状态机允许的后继动作，跳级的动作在页面上就点不到
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  待校验: ['提交校验'],
  数据正常: ['登记数据缺失'],
  数据缺失待复核: ['复核确认停用'],
  复核确认停用: ['复测恢复'],
  复测恢复: ['登记数据缺失'],
}

type FieldSpec = {
  name: string
  label: string
  required?: boolean
  type?: string
  placeholder?: string
}

const FORM_FIELDS: Record<string, FieldSpec[]> = {
  登记数据缺失: [
    { name: '当前完整率', label: '当前时段完整率(%)', type: 'number', placeholder: '如 72.4，不填则保留原值' },
    { name: '情况说明', label: '缺失情况说明', type: 'textarea', placeholder: '如：某层风速仪频繁掉线' },
  ],
  复核确认停用: [
    { name: '停用时间', label: '停用时间', type: 'date', required: true },
    { name: '停用前完整率', label: '停用前完整率(%)', type: 'number', placeholder: '封账值，如 65.1' },
    { name: '复核说明', label: '复核说明', type: 'textarea', placeholder: '如：数采模块损坏无法修复，确认停用' },
  ],
  复测恢复: [
    { name: '复测结论', label: '复测结论', required: true, type: 'textarea', placeholder: '如：各层风速比对偏差小于2%，具备恢复条件' },
    { name: '恢复时间', label: '恢复时间', type: 'date', required: true },
    { name: '恢复后完整率', label: '恢复后初始完整率(%)', type: 'number', placeholder: '可留空，恢复采集后再补录' },
    { name: '采集口径', label: '新时段采集口径', placeholder: '不填则沿用上一段口径' },
  ],
}

const form = reactive<{ action: string; row: Row | null; values: Record<string, string> }>({
  action: '',
  row: null,
  values: {},
})
const formError = ref('')

const formFields = computed<FieldSpec[]>(() => (form.action ? FORM_FIELDS[form.action] ?? [] : []))

function today() {
  return new Date().toISOString().slice(0, 10)
}

function availableActions(status: string | number | null): string[] {
  return ACTIONS_BY_STATUS[String(status ?? '')] ?? []
}

function needsForm(action: string): boolean {
  return action in FORM_FIELDS
}

function openForm(action: string, row: Row) {
  form.action = action
  form.row = row
  form.values = {}
  formError.value = ''
  if (action === '复核确认停用') {
    form.values['停用时间'] = today()
  }
  if (action === '复测恢复') {
    form.values['恢复时间'] = today()
  }
}

function closeForm() {
  form.action = ''
  form.row = null
  form.values = {}
  formError.value = ''
}

function ledger(row: Row): LedgerSegment[] {
  const value = row['完整率台账'] as unknown
  return Array.isArray(value) ? (value as LedgerSegment[]) : []
}

function rateText(row: Row): string {
  const value = row['数据完整率']
  return typeof value === 'string' && value ? value : '待采集'
}

function rateTitle(row: Row): string {
  const segments = ledger(row)
  if (!segments.length) {
    return '尚无采集时段'
  }
  return segments
    .map((seg) => {
      const span = seg.采集结束 ? `${seg.采集开始} ~ ${seg.采集结束}` : `${seg.采集开始} 起`
      const rate = seg.完整率 === null ? '采集中' : `${seg.完整率}%`
      return `${seg.label}：${span}，完整率 ${rate}\n采集口径：${seg.采集口径}`
    })
    .join('\n')
}

function opText(row: Row): string {
  const op = row['最近操作'] as OpRecord
  if (!op) {
    return '—'
  }
  return op.说明 ? `${op.动作}（${op.时间}）\n${op.说明}` : `${op.动作}（${op.时间}）`
}

function statusClass(status: string | number | null): string {
  const value = String(status ?? '')
  if (value === STATUS_STOPPED) return 'tag-stopped'
  if (value === '数据缺失待复核') return 'tag-missing'
  if (value === '复测恢复' || value === '数据正常') return 'tag-normal'
  return 'tag-pending'
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '测风塔登记入口尚未接入审批流'
}

async function postAction(action: string, row: Row, extra: Record<string, string> = {}) {
  errorMessage.value = ''
  try {
    const payload: Record<string, string> = { action, ...extra }
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    const result = (await response.json()) as { ok?: boolean; message?: string }
    if (!response.ok || !result.ok) {
      throw new Error(result.message || '测风塔动作未生效，请稍后重试')
    }
    closeForm()
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    const message = error instanceof Error ? error.message : '测风塔操作失败'
    if (form.action) {
      formError.value = message
    } else {
      errorMessage.value = message
    }
  }
}

function runDirectAction(action: string, row: Row) {
  void postAction(action, row)
}

function submitForm() {
  if (!form.action || !form.row) {
    return
  }
  void postAction(form.action, form.row, { ...form.values })
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (response.ok) {
      summary.value = (await response.json()) as Record<string, number>
    }
  } catch {
    // 统计加载失败不阻塞列表，卡片保持 0
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) {
    query.set('keyword', keyword.value.trim())
  }
  if (statusFilter.value) {
    query.set('status', statusFilter.value)
  }
  const suffix = query.toString()
  try {
    const response = await request(`${ENDPOINT}${suffix ? `?${suffix}` : ''}`)
    if (!response.ok) {
      throw new Error('测风塔列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '测风塔列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>
