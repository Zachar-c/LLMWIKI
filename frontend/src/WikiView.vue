<script setup>
import { computed, onMounted, ref, watch } from 'vue'

const props = defineProps({ active: Boolean })

const sources = ref([])
const pages = ref([])
const page = ref(null)
const selectedIds = ref([])
const topic = ref('')
const busy = ref(false)
const error = ref('')
const notice = ref('')
const savedContent = ref('')
const content = () => ({ title: page.value.title, sections: page.value.sections })
const dirty = computed(() => page.value?.status === 'draft' && JSON.stringify(content()) !== savedContent.value)

async function request(url, options = {}) {
  const response = await fetch(url, options)
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : '操作失败，请检查输入和服务状态。')
  }
  return response.json()
}
function adopt(result) {
  page.value = result
  savedContent.value = JSON.stringify(content())
}
function canLeave() { return !dirty.value || window.confirm('当前草稿有未保存的修改，确定离开吗？') }
async function refresh() {
  try {
    ;[sources.value, pages.value] = await Promise.all([request('/api/sources'), request('/api/wiki-pages')])
  } catch (e) { error.value = e.message }
}
async function select(id) {
  if (!canLeave()) return
  busy.value = true; error.value = ''; notice.value = ''
  try { adopt(await request(`/api/wiki-pages/${id}`)) } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function generate() {
  if (!canLeave()) return
  if (!topic.value.trim() || !selectedIds.value.length) { error.value = '请填写主题并至少选择一份资料。'; return }
  busy.value = true; error.value = ''; notice.value = ''
  try {
    adopt(await request('/api/wiki-drafts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topic: topic.value, source_ids: selectedIds.value }) }))
    await refresh()
    notice.value = '草稿已生成，请逐段核对原文后保存并发布。'
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function save() {
  busy.value = true; error.value = ''; notice.value = ''
  try {
    adopt(await request(`/api/wiki-pages/${page.value.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(content()) }))
    await refresh(); notice.value = '草稿已保存。'
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
async function publish() {
  if (dirty.value) { error.value = '请先保存修改，再核对原文并发布。'; return }
  busy.value = true; error.value = ''; notice.value = ''
  try {
    adopt(await request(`/api/wiki-pages/${page.value.id}/publish`, { method: 'POST' }))
    await refresh(); notice.value = '已发布。发布后页面保持不变。'
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
function evidence(id) { return page.value.evidence.find(item => item.id === id) }
onMounted(refresh)
watch(() => props.active, active => { if (active && !busy.value) refresh() })
</script>

<template>
  <section class="wiki" aria-label="Wiki 整理">
    <header><h1>知识 Wiki</h1><p>从选定资料生成草稿，逐段核对原文后发布。</p></header>
    <p v-if="error" class="error" role="alert">{{ error }}</p><p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <div class="wiki-grid">
      <aside><h2>整理资料</h2><label for="wiki-topic">主题</label><input id="wiki-topic" v-model="topic" maxlength="200" placeholder="例如：登录功能测试" />
        <p>选择资料（分段合计最多 12000 字符）：</p>
        <label v-for="source in sources" :key="source.id" class="source"><input v-model="selectedIds" type="checkbox" :value="source.id" /> {{ source.title }} · {{ source.version || '未标注版本' }}</label>
        <p v-if="!sources.length">请先在资料库导入文本。</p><button :disabled="busy" @click="generate">{{ busy ? '处理中…' : '生成草稿' }}</button>
        <h2>知识页</h2><button v-for="item in pages" :key="item.id" class="page-button" :disabled="busy" @click="select(item.id)">{{ item.title }} · {{ item.status === 'draft' ? '草稿' : '已发布' }}</button><p v-if="!pages.length">还没有知识页。</p>
      </aside>
      <article v-if="page"><div class="page-heading"><h2>{{ page.status === 'draft' ? '审阅草稿' : '已发布' }}</h2><span>#{{ page.id }}</span></div>
        <label for="wiki-title">标题</label><input id="wiki-title" v-model="page.title" :disabled="page.status !== 'draft' || busy" maxlength="200" />
        <div v-for="(section, index) in page.sections" :key="index" class="section">
          <label :for="`heading-${index}`">段落 {{ index + 1 }} 标题</label><input :id="`heading-${index}`" v-model="section.heading" :disabled="page.status !== 'draft' || busy" />
          <label :for="`text-${index}`">内容</label><textarea :id="`text-${index}`" v-model="section.text" :disabled="page.status !== 'draft' || busy" rows="5"></textarea>
          <p>原文依据：请检查以下片段是否支持本段内容。</p>
          <details v-for="id in section.chunk_ids" :key="id"><summary>片段 #{{ id }} · {{ evidence(id)?.title }} {{ evidence(id)?.version }}</summary><pre>{{ evidence(id)?.text }}</pre></details>
        </div>
        <div v-if="page.status === 'draft'" class="actions"><button :disabled="busy" @click="save">保存草稿</button><button :disabled="busy" @click="publish">确认原文并发布</button><span v-if="dirty">有未保存修改</span></div>
      </article>
      <article v-else><h2>选择知识页</h2><p>生成后可以编辑草稿并展开原文依据。</p></article>
    </div>
  </section>
</template>

<style scoped>
.wiki { padding: 24px; color: #253b36; }.wiki header { margin-bottom: 20px; }.wiki h1 { font-size: 26px; margin: 0; }.wiki h2 { font-size: 18px; }.wiki p { color: #5d6e65; line-height: 1.6; font-size: 14px; }.wiki-grid { display: grid; grid-template-columns: 270px minmax(0,1fr); gap: 16px; align-items: start; }.wiki aside, .wiki article { background: white; border: 1px solid #dce2d9; border-radius: 7px; padding: 20px; }.wiki label { display: block; margin: 14px 0 7px; font-size: 14px; }.wiki input:not([type=checkbox]), .wiki textarea { width: 100%; padding: 10px; border: 1px solid #ccd6ca; border-radius: 4px; color: inherit; font: inherit; }.wiki textarea { resize: vertical; line-height: 1.7; }.wiki .source { display: block; line-height: 1.6; }.wiki button { cursor: pointer; border: 1px solid #174c44; border-radius: 4px; background: #174c44; color: white; padding: 10px 14px; font: inherit; margin: 8px 0; }.wiki button:disabled { opacity: .6; cursor: default; }.wiki .page-button { display: block; width: 100%; text-align: left; background: white; color: #174c44; }.page-heading { display: flex; align-items: center; justify-content: space-between; }.section { padding: 12px 0 18px; border-bottom: 1px solid #dce2d9; }.wiki details { margin: 8px 0; padding: 10px; background: #f4f7f1; }.wiki summary { cursor: pointer; font-size: 14px; }.wiki pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.8; }.actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }.actions span { color: #826020; font-size: 13px; }.error,.notice { padding: 10px; border-radius: 4px; }.error { background: #fff0eb; color: #a33427 !important; }.notice { background: #e9f4eb; color: #205b3b !important; }@media (max-width: 800px) { .wiki-grid { grid-template-columns: 1fr; }.wiki { padding: 16px; } }
</style>
