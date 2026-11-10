<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import './cases.css'

const props = defineProps({ active: Boolean })

const sources = ref([])
const batches = ref([])
const selectedSources = ref([])
const requirement = ref('')
const batch = ref(null)
const cases = ref([])
const savedCases = ref('[]')
const confirmed = ref(false)
const busy = ref('')
const error = ref('')
const message = ref('')
const dirty = computed(() => JSON.stringify(cases.value) !== savedCases.value)
const reviewStale = computed(() => batch.value?.review_stale || dirty.value)

async function request(url, options) {
  let response
  try {
    response = await fetch(url, options)
  } catch {
    throw new Error('无法连接服务，请检查后端是否启动。')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `请求失败（${response.status}），请检查输入后重试。`)
  }
  return response.json()
}

function jsonRequest(method, data) {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }
}

function showBatch(value) {
  batch.value = value
  cases.value = value.cases.map(item => ({
    title: item.title,
    preconditions: item.preconditions,
    steps: [...item.steps],
    expected_result: item.expected_result,
    priority: item.priority,
  }))
  savedCases.value = JSON.stringify(cases.value)
  confirmed.value = false
}

async function refreshBatches() {
  batches.value = await request('/api/case-batches')
}

async function initialize() {
  busy.value = '加载中'
  error.value = ''
  try {
    const [available, history] = await Promise.all([request('/api/sources'), request('/api/case-batches')])
    sources.value = available
    batches.value = history
  } catch (failure) {
    error.value = failure.message
  } finally {
    busy.value = ''
  }
}

async function generate() {
  error.value = ''
  message.value = ''
  if (!requirement.value.trim() || !selectedSources.value.length) {
    error.value = '请填写需求并选择至少一份资料。'
    return
  }
  if (dirty.value && !window.confirm('当前用例有未保存的修改，继续生成会离开当前编辑内容。是否继续？')) return
  busy.value = '正在生成用例'
  try {
    const result = await request('/api/case-batches/generate', jsonRequest('POST', {
      requirement: requirement.value,
      source_ids: selectedSources.value,
    }))
    showBatch(result)
    message.value = '已生成用例草稿，请逐项核对后保存。'
    try { await refreshBatches() } catch { message.value += ' 历史列表刷新失败，可稍后重新加载。' }
  } catch (failure) {
    error.value = failure.message
  } finally {
    busy.value = ''
  }
}

async function openBatch(id) {
  if (dirty.value && !window.confirm('当前用例有未保存的修改，切换后这些修改将丢失。是否继续？')) return
  busy.value = '正在读取用例'
  error.value = ''
  message.value = ''
  try {
    showBatch(await request(`/api/case-batches/${id}`))
  } catch (failure) {
    error.value = failure.message
  } finally {
    busy.value = ''
  }
}

function setSteps(item, value) {
  item.steps = value.split('\n')
  confirmed.value = false
}

async function save() {
  error.value = ''
  message.value = ''
  if (!confirmed.value) {
    error.value = '请先逐项核对并勾选人工确认。'
    return
  }
  if (!cases.value.length || cases.value.some(item => !item.title.trim() || !item.expected_result.trim() || !item.steps.some(step => step.trim()))) {
    error.value = '每条用例都需要标题、至少一个步骤和预期结果。'
    return
  }
  busy.value = '正在保存'
  try {
    const cleaned = cases.value.map(item => ({ ...item, steps: item.steps.filter(step => step.trim()) }))
    const result = await request(`/api/case-batches/${batch.value.id}`, jsonRequest('PUT', { cases: cleaned, confirmed: true }))
    showBatch(result)
    message.value = '已保存人工核对后的用例。如内容有修改，请重新进行 AI 审查。'
    try { await refreshBatches() } catch { message.value += ' 历史列表刷新失败，可稍后重新加载。' }
  } catch (failure) {
    error.value = failure.message
  } finally {
    busy.value = ''
  }
}

async function review() {
  error.value = ''
  message.value = ''
  if (dirty.value) {
    error.value = '请先核对并保存当前修改，再进行 AI 审查。'
    return
  }
  busy.value = '正在审查'
  try {
    showBatch(await request(`/api/case-batches/${batch.value.id}/review`, { method: 'POST' }))
    message.value = '审查已完成，请结合需求和资料人工判断建议。'
  } catch (failure) {
    error.value = failure.message
  } finally {
    busy.value = ''
  }
}

async function exportCsv() {
  error.value = ''
  message.value = ''
  if (dirty.value) {
    error.value = '请先保存当前修改，再导出。'
    return
  }
  if (!batch.value.confirmed_at) {
    error.value = '请先人工核对并确认保存，再导出。'
    return
  }
  busy.value = '正在导出'
  try {
    const response = await fetch(`/api/case-batches/${batch.value.id}/export.csv`)
    if (!response.ok) throw new Error(`导出失败（${response.status}）。`)
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = `测试用例-${batch.value.id}.csv`
    link.click()
    URL.revokeObjectURL(url)
    message.value = '已导出保存的用例。'
  } catch (failure) {
    error.value = failure.message || '导出失败，请检查后端连接。'
  } finally {
    busy.value = ''
  }
}

onMounted(initialize)
watch(() => props.active, active => { if (active && !busy.value) initialize() })
</script>

<template>
  <section class="cases-workspace" aria-label="测试用例工作台">
    <div class="cases-heading"><div><p class="cases-eyebrow">02 / 测试用例</p><h1>从需求生成测试用例</h1><p>选择资料作为依据，生成后请人工核对，再保存和审查。</p></div></div>
    <p v-if="error" class="cases-alert" role="alert">{{ error }}</p>
    <p v-if="message" class="cases-success" role="status">{{ message }}</p>
    <p v-if="busy" class="cases-busy" role="status">{{ busy }}…</p>

    <div class="cases-layout">
      <aside class="cases-panel cases-input-panel">
        <h2>生成条件</h2>
        <label class="cases-label" for="case-requirement">需求描述</label>
        <textarea id="case-requirement" v-model="requirement" rows="7" :disabled="!!busy" placeholder="描述要测试的功能、规则和边界条件"></textarea>
        <fieldset class="cases-sources" :disabled="!!busy">
          <legend>选择参考资料 <span>至少一份</span></legend>
          <p v-if="!sources.length" class="cases-help">暂无资料，请先在资料库导入自编或公开文本。</p>
          <label v-for="source in sources" :key="source.id" class="cases-source">
            <input v-model="selectedSources" type="checkbox" :value="source.id" />
            <span>{{ source.title }}<small>{{ source.version || '未标注版本' }}</small></span>
          </label>
        </fieldset>
        <button class="cases-primary" type="button" :disabled="!!busy" @click="generate">生成用例</button>
        <div class="cases-history">
          <div class="cases-row"><h2>历史批次</h2><button type="button" class="cases-link" :disabled="!!busy" @click="initialize">刷新</button></div>
          <p v-if="!batches.length" class="cases-help">还没有生成记录。</p>
          <button v-for="item in batches" :key="item.id" type="button" class="cases-history-item" :class="{ active: batch?.id === item.id }" :disabled="!!busy" @click="openBatch(item.id)">
            <span>批次 #{{ item.id }}</span><small>{{ item.requirement }}</small>
          </button>
        </div>
      </aside>

      <div class="cases-results">
        <div v-if="!batch" class="cases-empty cases-panel"><h2>生成后在这里核对</h2><p>查看步骤、预期结果和原文依据，确认后可以保存并审查。</p></div>
        <template v-else>
          <section class="cases-panel cases-summary">
            <div class="cases-row"><div><p class="cases-eyebrow">批次 #{{ batch.id }}</p><h2>用例草稿 · {{ cases.length }} 条</h2></div><span v-if="dirty" class="cases-badge">有未保存修改</span></div>
            <p class="cases-requirement">{{ batch.requirement }}</p>
            <details class="cases-evidence">
              <summary>查看参考原文（{{ batch.evidence?.length || 0 }}）</summary>
              <p v-if="!batch.evidence?.length" class="cases-help">此批次未返回可展示的原文片段。</p>
              <article v-for="(item, index) in batch.evidence || []" :key="index">
                <strong v-if="item.kind === 'Wiki'">Wiki：{{ item.wiki_title }}</strong>
                <div v-for="original in (item.originals || [item])" :key="original.chunk_id">
                  <strong>{{ original.source_title }} · {{ original.version || '未标注版本' }} · 原文 #{{ original.chunk_id }}</strong>
                  <p>{{ original.text }}</p>
                </div>
              </article>
            </details>
          </section>

          <article v-for="(item, index) in cases" :key="index" class="cases-panel case-card">
            <div class="cases-row"><h2>用例 {{ index + 1 }}</h2><label class="cases-priority">优先级 <input v-model="item.priority" :disabled="!!busy" @input="confirmed = false" /></label></div>
            <label :for="`case-title-${index}`">标题</label><input :id="`case-title-${index}`" v-model="item.title" :disabled="!!busy" @input="confirmed = false" />
            <label :for="`case-preconditions-${index}`">前置条件</label><textarea :id="`case-preconditions-${index}`" v-model="item.preconditions" rows="2" :disabled="!!busy" @input="confirmed = false"></textarea>
            <label :for="`case-steps-${index}`">操作步骤 <span class="cases-help">每行一个步骤</span></label><textarea :id="`case-steps-${index}`" :value="item.steps.join('\n')" rows="4" :disabled="!!busy" @input="setSteps(item, $event.target.value)"></textarea>
            <label :for="`case-expected-${index}`">预期结果</label><textarea :id="`case-expected-${index}`" v-model="item.expected_result" rows="3" :disabled="!!busy" @input="confirmed = false"></textarea>
            <div v-for="(issue, issueIndex) in (batch.review?.issues || []).filter(issue => issue.case_index === index)" :key="issueIndex" class="cases-review-issue"><strong>审查建议{{ reviewStale ? '（可能已过期）' : '' }}</strong><p>{{ issue.description }}</p><p>{{ issue.suggestion }}</p></div>
          </article>

          <section class="cases-panel cases-actions">
            <label class="cases-confirm"><input v-model="confirmed" type="checkbox" :disabled="!!busy" /> 我已逐项核对用例内容和原文依据</label>
            <p class="cases-help">确认用于本次保存；AI 审查建议仍需人工判断。</p>
            <div class="cases-action-buttons"><button class="cases-primary" type="button" :disabled="!!busy" @click="save">确认并保存</button><button type="button" :disabled="!!busy" @click="review">AI 审查</button><button type="button" :disabled="!!busy" @click="exportCsv">导出 CSV</button></div>
            <p v-if="batch.review" class="cases-help">{{ reviewStale ? '用例已修改，已有审查结果可能过期。' : `当前审查共 ${batch.review.issues?.length || 0} 条建议。` }}</p>
          </section>
        </template>
      </div>
    </div>
  </section>
</template>
