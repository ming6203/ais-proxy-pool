import { request } from './client.ts'
import type {
  CreateProxyRequest,
  ProxyProbeRequest,
  ProxyProbeResponse,
  ProxyProfile,
  UpdateProxyProfileRequest,
} from '@/types'

export const proxiesApi = {
  list(): Promise<ProxyProfile[]> {
    return request<ProxyProfile[]>('/api/proxies')
  },

  create(req: CreateProxyRequest): Promise<ProxyProfile> {
    return request<ProxyProfile>('/api/proxies', {
      method: 'POST',
      body: JSON.stringify(req),
    })
  },

  update(id: string, req: UpdateProxyProfileRequest): Promise<ProxyProfile> {
    return request<ProxyProfile>(`/api/proxies/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(req),
    })
  },

  remove(id: string): Promise<{ ok: boolean; cleared_accounts: number }> {
    return request<{ ok: boolean; cleared_accounts: number }>(
      `/api/proxies/${encodeURIComponent(id)}`,
      { method: 'DELETE' },
    )
  },

  test(id: string): Promise<ProxyProfile> {
    return request<ProxyProfile>(`/api/proxies/${encodeURIComponent(id)}/test`, {
      method: 'POST',
    })
  },

  testUrl(req: ProxyProbeRequest): Promise<ProxyProbeResponse> {
    return request<ProxyProbeResponse>('/api/proxies/test', {
      method: 'POST',
      body: JSON.stringify(req),
    })
  },
}