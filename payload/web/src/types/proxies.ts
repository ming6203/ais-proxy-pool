export interface ProxyProfile {
  id: string
  name: string
  url: string
  url_masked: string
  notes: string
  created_at: string
  updated_at: string
  last_checked_at: number | null
  last_ok: boolean | null
  last_status: number | null
  last_latency_ms: number | null
  account_count: number
}

export interface CreateProxyRequest {
  name: string
  url: string
  notes?: string
}

export interface UpdateProxyProfileRequest {
  name?: string
  url?: string
  notes?: string
}

export interface ProxyProbeRequest {
  url: string
}

export interface ProxyProbeResponse {
  ok: boolean
  status: number
  latency_ms: number
  error: string
  proxy: string
}