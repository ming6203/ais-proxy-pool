import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { proxiesApi } from '@/api/proxies.ts'
import { useToastStore } from './toast.ts'
import type { CreateProxyRequest, ProxyProfile, UpdateProxyProfileRequest } from '@/types'

export const useProxyStore = defineStore('proxies', () => {
  const proxies = ref<ProxyProfile[]>([])
  const loading = ref(false)
  const testingId = ref<string | null>(null)

  const byId = computed<Record<string, ProxyProfile>>(() => {
    const map: Record<string, ProxyProfile> = {}
    for (const p of proxies.value) {
      map[p.id] = p
    }
    return map
  })

  async function fetchAll() {
    loading.value = true
    try {
      proxies.value = await proxiesApi.list()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '获取代理池失败'
      useToastStore().error(msg)
    } finally {
      loading.value = false
    }
  }

  async function create(req: CreateProxyRequest): Promise<ProxyProfile | null> {
    try {
      const created = await proxiesApi.create(req)
      useToastStore().success(`代理「${created.name}」已加入代理池`)
      await fetchAll()
      return created
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '新增代理失败'
      useToastStore().error(msg)
      return null
    }
  }

  async function update(
    id: string,
    req: UpdateProxyProfileRequest,
  ): Promise<ProxyProfile | null> {
    try {
      const updated = await proxiesApi.update(id, req)
      useToastStore().success(`代理「${updated.name}」已更新`)
      await fetchAll()
      return updated
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '更新代理失败'
      useToastStore().error(msg)
      return null
    }
  }

  async function remove(id: string): Promise<boolean> {
    try {
      const res = await proxiesApi.remove(id)
      useToastStore().success(
        res.cleared_accounts > 0
          ? `代理已删除，${res.cleared_accounts} 个账号恢复跟随全局代理`
          : '代理已删除',
      )
      await fetchAll()
      return true
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '删除代理失败'
      useToastStore().error(msg)
      return false
    }
  }

  async function test(id: string): Promise<ProxyProfile | null> {
    testingId.value = id
    try {
      const updated = await proxiesApi.test(id)
      if (updated.last_ok) {
        useToastStore().success(
          `「${updated.name}」连通正常 · HTTP ${updated.last_status} · ${updated.last_latency_ms ?? 0} ms`,
        )
      } else {
        useToastStore().error(
          `「${updated.name}」连接失败：HTTP ${updated.last_status ?? 0}`,
        )
      }
      await fetchAll()
      return updated
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '测试代理失败'
      useToastStore().error(msg)
      return null
    } finally {
      testingId.value = null
    }
  }

  function nameOf(id: string): string {
    return byId.value[id]?.name || ''
  }

  return {
    proxies,
    loading,
    testingId,
    byId,
    fetchAll,
    create,
    update,
    remove,
    test,
    nameOf,
  }
})