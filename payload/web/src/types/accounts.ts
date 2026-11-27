import type { AccountRotationStats } from './rotation.ts'

export interface Account {
  id: string
  name: string
  email: string | null
  created_at: string
  last_used?: string | null
  auth_user: string
  cookie_id?: string | null
  tier?: string
  enabled: boolean
  group: string
  notes?: string
  /** 账号独立出口代理：'' 跟随全局代理，'direct' 强制直连，或代理 URL */
  /** 代理池中的命名代理引用；优先于上面的自定义 URL */
  proxy_id?: string
  /** 解析后的代理名（自定义 URL 或未设置时为空） */
  proxy_name?: string
}

export type AccountWithStats = Omit<Account, 'last_used' | 'auth_user' | 'email'> &
  Partial<AccountRotationStats> & {
    auth_user: string
    email: string | null
    last_used?: string | null
  }

export interface AccountPreset {
  id: string
  name: string
  description?: string
  action: 'snapshot' | 'enable_all' | 'disable_all' | 'filter_tier' | 'filter_group' | string
  account_ids: string[]
  target_tiers: string[]
  target_groups: string[]
  is_system: boolean
  created_at?: string
  updated_at?: string
}

export interface CreatePresetRequest {
  name: string
  description?: string
  action?: string
  account_ids?: string[]
  target_tiers?: string[]
  target_groups?: string[]
}

export interface SnapshotPresetRequest {
  name: string
  description?: string
}

export interface ApplyPresetResponse {
  ok: boolean
  preset_id: string
  preset_name: string
  enabled_count: number
  disabled_count: number
  enabled_account_ids: string[]
  disabled_account_ids: string[]
}

export interface ImportCookiesRequest {
  cookies: string
  name?: string
  email?: string
  account_id?: string
  auth_user?: string
  tier?: string
  proxy_id?: string
}

export interface ImportCookiesResponse {
  account_id: string
  name: string
  cookie_count: number
  auth_user: string
  tier?: string
}

export interface ProbeAndImportRequest {
  cookies: string
  name_prefix?: string
  proxy_id?: string
}

export interface ProbeAndImportResponse {
  imported_count: number
  accounts: Account[]
}

export interface BundleAccountItem {
  id?: string
  name?: string
  email?: string
  cookies: string
  auth_user?: string
  tier?: string
  proxy_id?: string
}

export interface ImportBundleRequest {
  file_path?: string
  content?: string
  accounts?: BundleAccountItem[]
}

export interface ImportBundleResponse {
  imported_count: number
  accounts: Account[]
}
