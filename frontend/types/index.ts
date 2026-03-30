// Types for the Invoice Handler SaaS

export type Plan = 'free' | 'pro' | 'enterprise';

export interface Tenant {
  id: number;
  name: string;
  slug: string;
  plan: Plan;
  subscription_status: string;
  is_active: boolean;
  created_at: string;
}

export interface User {
  id: number;
  email: string;
  full_name?: string;
}

export interface Invoice {
  id: number;
  invoice_number: string;
  vendor_name: string;
  amount_due: number;
  amount_paid: number;
  currency: string;
  invoice_date: string;
  due_date: string;
  status: 'pending' | 'paid' | 'overdue' | 'disputed';
  description?: string;
  source: string;
  needs_review: boolean;
  reminder_count: number;
}

export interface Customer {
  id: number;
  email: string;
  phone?: string;
  full_name?: string;
  company_name?: string;
}

export interface ConnectedAccount {
  id: number;
  provider: 'google' | 'quickbooks' | 'xero' | 'plaid';
  is_active: boolean;
  connected_at: string;
  expires_at?: string;
  last_synced_at?: string;
}

export interface DashboardStats {
  total_invoices: number;
  overdue_count: number;
  overdue_amount: number;
  paid_count: number;
  reconciliation_rate: number;
  pending_count: number;
  pending_amount: number;
  this_month_invoices: number;
  this_month_revenue: number;
}

export interface Activity {
  id: number;
  type: string;
  description: string;
  timestamp: string;
  status?: string;
}

export interface WorkflowRun {
  id: number;
  invocation_id: string;
  workflow_type: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  current_step?: string;
  progress: number;
  error_message?: string;
  created_at: string;
  completed_at?: string;
}

export interface UsageRecord {
  month: string;
  invoices_used: number;
  invoices_limit: number;
  emails_used: number;
  emails_limit: number;
  sms_used: number;
  sms_limit: number;
  api_calls: number;
}

export interface PlanLimits {
  name: string;
  description: string;
  invoices_per_month: number;
  emails_per_month: number;
  sms_per_month: number;
  api_access: boolean;
  users_per_tenant: number;
  sources: string[];
  report_history: number;
  price_monthly: number;
  price_yearly: number;
}

export interface APIKey {
  id: number;
  name: string;
  prefix: string;
  last_used_at?: string;
  created_at: string;
}

export interface PlanInfo {
  id: string;
  name: string;
  description: string;
  price_monthly: number;
  price_yearly: number;
  features: string[];
}

export interface Subscription {
  plan: string;
  status: string;
  is_active: boolean;
  renews_at?: string;
}
