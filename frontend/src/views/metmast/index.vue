<template>
  <section class="page" data-module="metmast">
    <header class="page-head">
      <div>
        <h2>测风塔管理</h2>
        <p class="page-desc">
          停用与恢复按流程走：数据缺失待复核 → 复核确认停用 → 复测恢复，不允许跳级；
          停用期间不允许提交校验，恢复使用须登记复测结论与恢复时间。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记测风塔</button>
        <button class="btn" type="button" @click="exportRows">导出测风塔清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>塔架编号</span>
        <input v-model="filters.keyword" placeholder="按塔架编号检索" />
      </label>
      <label class="filter-item">
        <span>测风状态</span>
        <select v-model="filters.status">
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
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>最近操作记录</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <span v-if="column === '测风状态'" class="status-tag" :data-status="row[column]">{{ row[column] }}</span>
            <span v-else>{{ row[column] ?? '—' }}</span>
          </td>
          <td class="action-cell">
            <template v-if="row.last_action">
              <div>{{ row.last_action.action }} · {{ row.last_action.time }}</div>
              <div class="action-note" v-if="row.last_action.note">{{ row.last_action.note }}</div>
            </template>
            <span v-else class="muted">暂无停用/恢复记录</span>
          </td>
          <td class="row-actions">
            <button
              v-for="action in allowedActions(row)"
              :key="action"
              class="link"
              :class="{ danger: action === '复核确认停用' }"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无符合条件的测风塔</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条测风塔记录；在运台数与运营概览同一口径</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="dialog.action" class="modal-mask" @click.self="closeDialog">
      <form class="modal" @submit.prevent="submitDialog">
        <h3>{{ dialog.action }} · {{ dialog.tower }}</h3>

        <template v-if="dialog.action === '登记数据缺失'">
          <label class="modal-field">
            <span>当前数据完整率</span>
            <input v-model="dialog.form.数据完整率" placeholder="如 62.3%" />
          </label>
          <label class="modal-field">
            <span>登记时间</span>
            <input v-model="dialog.form.操作时间" type="date" />
          </label>
        </template>

        <template v-else-if="dialog.action === '复核确认停用'">
          <label class="modal-field">
            <span>停用原因 / 复核说明</span>
            <textarea v-model="dialog.form.停用原因" rows="3" placeholder="复核后确认停用的依据"></textarea>
          </label>
          <label class="modal-field">
            <span>停用时间</span>
            <input v-model="dialog.form.操作时间" type="date" />
          </label>
          <p class="modal-tip">停用后塔架高度、测风层数仍可查看，停用期间不允许提交校验。</p>
        </template>

        <template v-else-if="dialog.action === '复测恢复'">
          <label class="modal-field">
            <span>复测结论 <em>*</em></span>
            <textarea v-model="dialog.form.复测结论" rows="3" placeholder="如：复测合格，各层风速偏差在允许范围内"></textarea>
          </label>
          <label class="modal-field">
            <span>恢复时间 <em>*</em></span>
            <input v-model="dialog.form.恢复时间" type="date" required />
          </label>
          <label class="modal-field">
            <span>恢复后数据完整率</span>
            <input v-model="dialog.form.数据完整率" placeholder="恢复采集后的完整率，如 97.8%" />
          </label>
          <p class="modal-tip">恢复后另起采集时段，停用前后的完整率分开统计。</p>
        </template>

        <template v-else-if="dialog.action === '登记测风塔'">
          <label class="modal-field">
            <span>塔架编号 <em>*</em></span>
            <input v-model="dialog.form.塔架编号" required />
          </label>
          <label class="modal-field">
            <span>所在场站 <em>*</em></span>
            <input v-model="dialog.form.所在场站" required />
          </label>
          <label class="modal-field">
            <span>塔架高度 <em>*</em></span>
            <input v-model="dialog.form.塔架高度" placeholder="如 100m" required />
          </label>
          <label class="modal-field">
            <span>测风层数</span>
            <input v-model="dialog.form.测风层数" placeholder="如 7层" />
          </label>
          <label class="modal-field">
            <span>风速仪型号</span>
            <input v-model="dialog.form.风速仪型号" />
          </label>
          <label class="modal-field">
            <span>当前数据完整率</span>
            <input v-model="dialog.form.数据完整率" placeholder="如 98.6%" />
          </label>
        </template>

        <p v-if="dialog.error" class="error-text">{{ dialog.error }}</p>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeDialog">取消</button>
          <button class="btn primary" type="submit" :disabled="dialog.saving">
            {{ dialog.saving ? '提交中…' : '确认提交' }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type LastAction = { action: string; time: string; note?: string } | null
type Row = Record<string, string | number | null> & { last_action?: LastAction }

const ENDPOINT = '/api/metmast'
const columns = [
  '塔架编号',
  '所在场站',
  '塔架高度',
  '测风层数',
  '风速仪型号',
  '上次校验日',
  '停用前数据完整率',
  '恢复后数据完整率',
  '测风状态',
]
const statuses = ['在运', '数据缺失待复核', '复核确认停用', '复测恢复']

// 状态 → 允许动作：只能沿流水线推进，不允许跳级；停用期间不提供提交校验
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  在运: ['提交校验', '登记数据缺失'],
  复测恢复: ['提交校验', '登记数据缺失'],
  数据缺失待复核: ['复核确认停用'],
  复核确认停用: ['复测恢复'],
}

const statsDefault = [
  { label: '测风塔总数', value: 0 },
  { label: '在运测风塔', value: 0 },
  { label: '数据缺失待复核', value: 0 },
  { label: '复核确认停用', value: 0 },
]
const stats = ref(statsDefault.map((item) => ({ ...item })))

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<{ keyword: string; status: string }>({ keyword: '', status: '' })

const dialog = reactive<{
  action: string
  tower: string
  targetId: number | null
  form: Record<string, string>
  error: string
  saving: boolean
}>({ action: '', tower: '', targetId: null, form: {}, error: '', saving: false })

function allowedActions(row: Row): string[] {
  return ACTIONS_BY_STATUS[String(row['测风状态'])] ?? []
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  Object.assign(dialog, {
    action: '登记测风塔',
    tower: '',
    targetId: null,
    form: {},
    error: '',
    saving: false,
  })
}

function runAction(action: string, row: Row) {
  Object.assign(dialog, {
    action,
    tower: String(row['塔架编号'] ?? ''),
    targetId: Number(row.id),
    form: {},
    error: '',
    saving: false,
  })
}

function closeDialog() {
  dialog.action = ''
  dialog.targetId = null
  dialog.form = {}
  dialog.error = ''
}

async function submitDialog() {
  dialog.error = ''
  dialog.saving = true
  try {
    if (dialog.action === '登记测风塔') {
      const response = await request(ENDPOINT, {
        method: 'POST',
        body: JSON.stringify({ values: { ...dialog.form } }),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message ?? '测风塔登记失败')
      }
    } else {
      const response = await request(`${ENDPOINT}/${dialog.targetId}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action: dialog.action, ...dialog.form } }),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message ?? '操作未生效，请稍后重试')
      }
    }
    closeDialog()
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    dialog.error = error instanceof Error ? error.message : '操作失败'
  } finally {
    dialog.saving = false
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const data = await response.json()
    stats.value = [
      { label: '测风塔总数', value: data.total ?? 0 },
      { label: '在运测风塔', value: data.active ?? 0 },
      { label: '数据缺失待复核', value: data.missing ?? 0 },
      { label: '复核确认停用', value: data.stopped ?? 0 },
    ]
  } catch {
    // 统计读取失败不阻塞列表
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  if (filters.value.keyword) params.set('keyword', filters.value.keyword)
  if (filters.value.status) params.set('status', filters.value.status)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('测风塔列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '测风塔列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>

<style scoped>
.muted {
  color: var(--muted);
  font-size: 12px;
}
.action-cell {
  font-size: 12px;
  white-space: nowrap;
}
.action-note {
  color: var(--muted);
  margin-top: 2px;
  max-width: 220px;
  white-space: normal;
}
.row-actions .link.danger {
  color: #c0392b;
}
.status-tag {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  border: 1px solid var(--border);
}
.status-tag[data-status='在运'],
.status-tag[data-status='复测恢复'] {
  background: #e8f6ee;
  border-color: #9bd4b3;
  color: #1f7a45;
}
.status-tag[data-status='数据缺失待复核'] {
  background: #fdf3e0;
  border-color: #e8c387;
  color: #9a6a13;
}
.status-tag[data-status='复核确认停用'] {
  background: #fdeceb;
  border-color: #e3a5a0;
  color: #a33a32;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  width: 420px;
  background: #fff;
  border-radius: 8px;
  padding: 18px 20px;
}
.modal h3 {
  margin: 0 0 12px;
  font-size: 16px;
}
.modal-field {
  display: block;
  margin-bottom: 10px;
}
.modal-field span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}
.modal-field input,
.modal-field textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font: inherit;
}
.modal-field em {
  color: #c0392b;
  font-style: normal;
}
.modal-tip {
  font-size: 12px;
  color: var(--muted);
  margin: 4px 0 10px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
</style>
