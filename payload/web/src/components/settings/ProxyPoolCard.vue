<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useProxyStore } from '@/stores/proxies.ts'
import { proxiesApi } from '@/api/proxies.ts'
import Button from '@/components/ui/Button.vue'
import {
  Layers,
  Plus,
  Server,
  Pencil,
  Trash2,
  PlugZap,
  CheckCircle2,
  AlertTriangle,
  X,
  Save,
  Users,
} from 'lucide-vue-next'
import type { ProxyProfile } from '@/types'

const proxyStore = useProxyStore()

const editingId = ref<string | null>(null)
const showForm = ref(false)
const saving = ref(false)
const probing = ref(false)
const probeResult = ref<{ ok: boolean; text: string } | null>(null)

const form = reactive({
  name: '',
  url: '',
  notes: '',
})

onMounted(() => {
  void proxyStore.fetchAll()
})

function resetForm() {
  form.name = ''
  form.url = ''
  form.notes = ''
  probeResult.value = null
  editingId.value = null
  showForm.value = false
}

function startCreate() {
  resetForm()
  showForm.value = true
}

function startEdit(profile: ProxyProfile) {
  editingId.value = profile.id
  form.name = profile.name
  form.url = profile.url
  form.notes = profile.notes || ''
  probeResult.value = null
  showForm.value = true
}

async function handleProbe() {
  if (!form.url.trim()) return
  probing.value = true
  probeResult.value = null
  try {
    const res = await proxiesApi.testUrl({ url: form.url.trim() })
    probeResult.value = res.ok
      ? { ok: true, text: `连通正常 · HTTP ${res.status} · ${res.latency_ms} ms` }
      : { ok: false, text: `连接失败：${res.error || `HTTP ${res.status}`}` }
  } catch (err: unknown) {
    probeResult.value = {
      ok: false,
      text: err instanceof Error ? err.message : '测试失败',
    }
  } finally {
    probing.value = false
  }
}

async function handleSave() {
  if (!form.name.trim() || !form.url.trim()) return
  saving.value = true
  try {
    if (editingId.value) {
      const updated = await proxyStore.update(editingId.value, {
        name: form.name.trim(),
        url: form.url.trim(),
        notes: form.notes.trim(),
      })
      if (updated) resetForm()
    } else {
      const created = await proxyStore.create({
        name: form.name.trim(),
        url: form.url.trim(),
        notes: form.notes.trim(),
      })
      if (created) resetForm()
    }
  } finally {
    saving.value = false
  }
}

async function handleDelete(profile: ProxyProfile) {
  const hint = profile.account_count
    ? `该代理正被 ${profile.account_count} 个账号使用，删除后这些账号会恢复跟随全局代理。确认删除「${profile.name}」？`
    : `确认删除代理「${profile.name}」？`
  if (!window.confirm(hint)) return
  const ok = await proxyStore.remove(profile.id)
  if (ok && editingId.value === profile.id) resetForm()
}

function formatChecked(ts: number | null): string {
  if (!ts) return '未测试'
  return new Date(ts * 1000).toLocaleString()
}
</script>

<template>
  <div class="bg-white border border-gray-200/80 rounded-2xl p-6 shadow-xs space-y-5">
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-gray-100 pb-4">
      <div class="flex items-center gap-2.5">
        <div class="p-2 rounded-xl bg-indigo-50 text-indigo-600 border border-indigo-100">
          <Layers class="w-5 h-5" />
        </div>
        <div>
          <h3 class="font-semibold text-gray-900 text-sm flex items-center gap-2">
            <span>代理池</span>
            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-indigo-100 text-indigo-800">
              {{ proxyStore.proxies.length }} 个命名代理
            </span>
          </h3>
          <p class="text-[11px] text-gray-400 mt-0.5">
            给每个代理起名后，在账号管理里直接按名字分配，一号一代理；地址与凭据保存在 data/proxies.json，不写入仓库
          </p>
        </div>
      </div>
      <Button
        variant="primary"
        size="sm"
        @click="startCreate"
      >
        <Plus class="w-3.5 h-3.5" />
        <span>新增代理</span>
      </Button>
    </div>

    <!-- Add / edit form -->
    <div
      v-if="showForm"
      class="p-4 bg-gray-50/70 border border-gray-200/70 rounded-2xl space-y-3"
    >
      <div class="flex items-center justify-between">
        <div class="text-xs font-semibold text-gray-700">
          {{ editingId ? '编辑代理' : '新增代理' }}
        </div>
        <button
          type="button"
          class="text-gray-400 hover:text-gray-700"
          @click="resetForm"
        >
          <X class="w-4 h-4" />
        </button>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div class="space-y-1">
          <label class="block text-[11px] font-semibold text-gray-600">代理名称</label>
          <input
            v-model="form.name"
            type="text"
            placeholder="例如：香港-01 / 日本-住宅-3"
            class="w-full px-3 py-2 bg-white border border-gray-200 rounded-xl text-xs outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
          >
        </div>
        <div class="space-y-1 md:col-span-2">
          <label class="block text-[11px] font-semibold text-gray-600">代理地址</label>
          <input
            v-model="form.url"
            type="text"
            spellcheck="false"
            placeholder="socks5://user:pass@host:1080 或 http://host:7890"
            class="w-full px-3 py-2 bg-white border border-gray-200 rounded-xl text-xs font-mono outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
          >
        </div>
      </div>

      <div class="space-y-1">
        <label class="block text-[11px] font-semibold text-gray-600">备注（可选）</label>
        <input
          v-model="form.notes"
          type="text"
          placeholder="例如：住宅 IP / 到期 2027-03 / 仅用于 Pro 账号"
          class="w-full px-3 py-2 bg-white border border-gray-200 rounded-xl text-xs outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20"
        >
      </div>

      <div
        v-if="probeResult"
        class="p-2.5 rounded-xl flex items-start gap-2 text-xs border"
        :class="probeResult.ok
          ? 'bg-emerald-50/80 border-emerald-200 text-emerald-800'
          : 'bg-rose-50/80 border-rose-200 text-rose-800'"
      >
        <CheckCircle2
          v-if="probeResult.ok"
          class="w-3.5 h-3.5 shrink-0 mt-0.5"
        />
        <AlertTriangle
          v-else
          class="w-3.5 h-3.5 shrink-0 mt-0.5"
        />
        <span class="break-all">{{ probeResult.text }}</span>
      </div>

      <div class="flex items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          :loading="saving"
          :disabled="!form.name.trim() || !form.url.trim()"
          @click="handleSave"
        >
          <Save class="w-3.5 h-3.5" />
          <span>{{ editingId ? '保存修改' : '加入代理池' }}</span>
        </Button>
        <Button
          variant="secondary"
          size="sm"
          :loading="probing"
          :disabled="!form.url.trim()"
          @click="handleProbe"
        >
          <PlugZap class="w-3.5 h-3.5" />
          <span>测试连通性</span>
        </Button>
        <span class="text-[11px] text-gray-400">支持 http / https / socks5 / socks5h</span>
      </div>
    </div>

    <!-- Empty state -->
    <div
      v-if="!proxyStore.proxies.length"
      class="p-8 text-center border border-dashed border-gray-200 rounded-2xl bg-gray-50/40"
    >
      <Server class="w-8 h-8 text-gray-300 mx-auto mb-2" />
      <p class="text-xs text-gray-500">
        代理池还是空的。先添加几个命名代理，再去账号管理里按名字分配。
      </p>
    </div>

    <!-- List -->
    <div
      v-else
      class="space-y-2"
    >
      <div
        v-for="profile in proxyStore.proxies"
        :key="profile.id"
        class="p-3 border rounded-xl transition-colors"
        :class="editingId === profile.id
          ? 'border-indigo-300 bg-indigo-50/30'
          : 'border-gray-200/80 hover:border-gray-300'"
      >
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div class="min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="font-semibold text-xs text-gray-900">{{ profile.name }}</span>
              <span
                v-if="profile.account_count"
                class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-100 text-emerald-800"
              >
                <Users class="w-2.5 h-2.5" /> {{ profile.account_count }} 个账号
              </span>
              <span
                v-else
                class="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-500"
              >
                未分配
              </span>
              <span
                v-if="profile.last_ok === true"
                class="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-700"
              >
                <CheckCircle2 class="w-2.5 h-2.5" /> {{ profile.last_latency_ms ?? 0 }}ms
              </span>
              <span
                v-else-if="profile.last_ok === false"
                class="inline-flex items-center gap-1 text-[10px] font-semibold text-rose-700"
              >
                <AlertTriangle class="w-2.5 h-2.5" /> 失败
              </span>
            </div>
            <div class="text-[11px] font-mono text-gray-500 truncate mt-0.5">
              {{ profile.url_masked || profile.url }}
            </div>
            <div
              v-if="profile.notes"
              class="text-[11px] text-gray-400 truncate mt-0.5"
            >
              {{ profile.notes }}
            </div>
            <div class="text-[10px] text-gray-400 mt-0.5">
              最近测试：{{ formatChecked(profile.last_checked_at) }}
            </div>
          </div>

          <div class="flex items-center gap-1 shrink-0">
            <Button
              variant="secondary"
              size="sm"
              :loading="proxyStore.testingId === profile.id"
              @click="proxyStore.test(profile.id)"
            >
              <PlugZap class="w-3 h-3" />
              <span>测试</span>
            </Button>
            <button
              type="button"
              class="p-1.5 text-gray-400 hover:text-indigo-600 hover:bg-gray-100 rounded-lg transition-colors cursor-pointer"
              title="编辑名称/地址/备注"
              @click="startEdit(profile)"
            >
              <Pencil class="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              class="p-1.5 text-gray-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors cursor-pointer"
              title="删除代理"
              @click="handleDelete(profile)"
            >
              <Trash2 class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>