// ── Domain types for GABI DOU ──

export type DOSection = "DO1" | "DO2" | "DO3";

export const SECTION_COLORS: Record<DOSection, string> = {
  DO1: "bg-do1/15 text-do1 border-do1/30",
  DO2: "bg-do2/15 text-do2 border-do2/30",
  DO3: "bg-do3/15 text-do3 border-do3/30",
};

// ── Auth ──
export type UserRole = "visitor" | "user" | "admin";

export interface User {
  id: string;
  userId?: string;
  name: string;
  email: string;
  role: UserRole;
  roles: UserRole[];
  avatarUrl?: string;
  lastLoginAt: string;
  createdAt: string;
  status: "active" | "suspended";
  sessionSource?: string;
  isServiceAccount?: boolean;
  /** When false, show email verification banner. Default true for token/session users. */
  emailVerified?: boolean;
}

export interface AdminStats {
  totalUsers: number;
  activeUsers: number;
  adminCount: number;
  totalConversations: number;
  recentLogins: { userId: string; name: string; email: string; loginAt: string }[];
  systemStatus: "operational" | "degraded" | "down";
}

export interface ChatUsageStats {
  totalConversations: number;
  avgPerUser: number;
  recentErrors: { id: string; message: string; timestamp: string }[];
  topUsers: { userId: string; name: string; count: number }[];
  dailyVolume: { date: string; count: number }[];
}

export interface FeatureFlag {
  id: string;
  label: string;
  description: string;
  enabled: boolean;
}

export interface IntegrationStatus {
  name: string;
  status: "ok" | "warning" | "critical";
  lastChecked: string;
}

export interface Document {
  id: string;
  title: string;
  summary: string;
  body: string;
  section: DOSection;
  organ: string;
  publishedAt: string; // ISO date
  tags: string[];
  toc: TocEntry[];
}

export interface TocEntry {
  id: string;
  label: string;
  level: number; // 1 | 2 | 3
}

export interface SearchResult {
  id: string;
  title: string;
  snippet: string;
  section: DOSection;
  organ: string;
  publishedAt: string;
  relevance: number; // 0–1
  tags: string[];
}

export interface SearchFilters {
  query: string;
  section?: DOSection;
  organ?: string;
  dateFrom?: string;
  dateTo?: string;
  tags?: string[];
}

export interface KPIData {
  label: string;
  value: number;
  change?: number;
  changeLabel?: string;
  sparkline: number[];
  unit?: string;
}

export interface VolumeDataPoint {
  date: string;
  do1: number;
  do2: number;
  do3: number;
}

export interface OrganActivity {
  organ: string;
  count: number;
}

export interface ActTypeData {
  type: string;
  count: number;
  percentage: number;
}

export interface SectionTotalData {
  section: DOSection;
  count: number;
  percentage: number;
}

export interface AnalyticsData {
  volume: VolumeDataPoint[];
  organActivity: OrganActivity[];
  actTypes: ActTypeData[];
  sectionTotals: SectionTotalData[];
  kpis: KPIData[];
  latestDocuments: Document[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string; // ISO
  citations?: { documentId: string; title: string }[];
}

export interface ChatThread {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: string;
}
