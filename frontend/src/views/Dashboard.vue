<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常；测风塔在运台数与测风塔台账同一口径。</p>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th><th>在运数</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
          <td>{{ row.active ?? '—' }}</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number; active?: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])

function fallbackModules(): Overview['modules'] {
  const names = ['风电场站', '风电机组', '叶片', '齿轮箱', '发电机', '变桨系统', '偏航系统', '测风塔', '集电线路', '升压站', '功率预测', '振动监测', '缺陷登记', '检修任务', '备件领用', '巡视检查', '验收确认', '电量结算']
  return names.map((name) => ({ name, created: 0, pending: 0, abnormal: 0 }))
}

onMounted(async () => {
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
  } catch {
    cards.value = [
      { label: '业务模块', value: 0 },
      { label: '今日新增', value: 0 },
      { label: '待处理', value: 0 },
      { label: '异常量', value: 0 },
      { label: '测风塔在运台数', value: 0 },
    ]
    moduleRows.value = fallbackModules()
  }
})
</script>
