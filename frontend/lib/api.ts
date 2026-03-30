// API client for communicating with the backend

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

class ApiClient {
  private token: string | null = null;

  setToken(token: string | null) {
    this.token = token;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    if (this.token) {
      (headers as Record<string, string>)['Authorization'] = `Bearer ${this.token}`;
    }

    const response = await fetch(`${API_URL}${endpoint}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'An error occurred' }));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    return response.json();
  }

  // ============ TENANT ============
  async getTenant() {
    return this.request<any>('/api/v1/tenants/me');
  }

  async createTenant(name: string, slug: string) {
    return this.request<any>('/api/v1/tenants', {
      method: 'POST',
      body: JSON.stringify({ name, slug }),
    });
  }

  async updateTenant(data: { name?: string }) {
    return this.request<any>('/api/v1/tenants/me', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async getPlanLimits() {
    return this.request<any>('/api/v1/tenants/me/limits');
  }

  // ============ DASHBOARD ============
  async getDashboardStats() {
    return this.request<any>('/api/v1/dashboard/stats');
  }

  async getRecentActivity(limit = 10) {
    return this.request<any[]>(`/api/v1/dashboard/activity?limit=${limit}`);
  }

  // ============ WORKFLOWS ============
  async runWorkflow(workflowType: string, sources?: string[]) {
    return this.request<any>('/api/v1/workflows/run', {
      method: 'POST',
      body: JSON.stringify({ workflow_type: workflowType, sources }),
    });
  }

  async getWorkflowStatus(invocationId: string) {
    return this.request<any>(`/api/v1/workflows/${invocationId}`);
  }

  async getWorkflows(limit = 20, status?: string) {
    const params = new URLSearchParams({ limit: limit.toString() });
    if (status) params.append('status', status);
    return this.request<any[]>(`/api/v1/workflows?${params}`);
  }

  // ============ CONNECTIONS ============
  async getConnections() {
    return this.request<any[]>('/api/v1/connections');
  }

  async disconnectProvider(provider: string) {
    return this.request(`/api/v1/connections/${provider}/disconnect`, {
      method: 'POST',
    });
  }

  // ============ OAUTH ============
  async getGoogleAuthUrl() {
    return this.request<{ auth_url: string }>('/oauth/google/auth');
  }

  async getQuickBooksAuthUrl() {
    return this.request<{ auth_url: string }>('/oauth/quickbooks/auth');
  }

  async getXeroAuthUrl() {
    return this.request<{ auth_url: string }>('/oauth/xero/auth');
  }

  async createPlaidLinkToken() {
    return this.request<{ link_token: string }>('/oauth/plaid/link-token', {
      method: 'POST',
    });
  }

  async exchangePlaidToken(publicToken: string) {
    return this.request('/oauth/plaid/exchange', {
      method: 'POST',
      body: JSON.stringify({ public_token: publicToken }),
    });
  }

  async getOAuthProviders() {
    return this.request<any[]>('/oauth/providers');
  }

  // ============ BILLING ============
  async getSubscription() {
    return this.request<any>('/billing/subscription');
  }

  async getAvailablePlans() {
    return this.request<any[]>('/billing/plans');
  }

  async upgradePlan(plan: string, billingCycle: string = 'monthly') {
    return this.request<{ url: string }>('/billing/upgrade', {
      method: 'POST',
      body: JSON.stringify({ plan, billing_cycle: billingCycle }),
    });
  }

  async cancelSubscription() {
    return this.request('/billing/cancel', { method: 'POST' });
  }

  async openCustomerPortal() {
    return this.request<{ url: string }>('/billing/portal', { method: 'POST' });
  }

  // ============ USAGE ============
  async getUsage() {
    return this.request<any>('/api/v1/usage');
  }

  async initializeUsage() {
    return this.request('/api/v1/usage/initialize', { method: 'POST' });
  }

  // ============ API KEYS ============
  async createApiKey(name: string) {
    return this.request<{ api_key: string; name: string }>('/api/v1/api-keys', {
      method: 'POST',
      body: JSON.stringify({ name }),
    });
  }

  async getApiKeys() {
    return this.request<any[]>('/api/v1/api-keys');
  }

  async revokeApiKey(id: number) {
    return this.request(`/api/v1/api-keys/${id}`, { method: 'DELETE' });
  }

  // ============ MEMBERS ============
  async getMembers() {
    return this.request<any[]>('/api/v1/members');
  }

  // ============ INVOICES ============
  async getInvoices(params?: { status?: string; page?: number; per_page?: number }) {
    const query = new URLSearchParams(params as Record<string, string>);
    return this.request<{ data: any[]; total: number; page: number; per_page: number; total_pages: number }>(`/invoices?${query}`);
  }

  async getInvoice(id: number) {
    return this.request<any>(`/invoices/${id}`);
  }

  async createInvoice(data: any) {
    return this.request<any>('/invoices', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // ============ REPORTS ============
  async getReports(params?: { type?: string }) {
    const query = new URLSearchParams(params as Record<string, string>);
    return this.request<{ data: any[] }>(`/reports?${query}`);
  }

  async generateReport(type: string, startDate: string, endDate: string) {
    return this.request('/reports/generate', {
      method: 'POST',
      body: JSON.stringify({ report_type: type, period_start: startDate, period_end: endDate }),
    });
  }

  // ============ EXPENSES ============
  async getExpenses(params?: { category?: string; page?: number; limit?: number }) {
    const query = new URLSearchParams(params as Record<string, string>);
    return this.request<{ data: any[]; total: number }>(`/expenses?${query}`);
  }

  async getExpense(id: number) {
    return this.request<any>(`/expenses/${id}`);
  }

  async createExpense(data: any) {
    return this.request<any>('/expenses', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateExpense(id: number, data: any) {
    return this.request<any>(`/expenses/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteExpense(id: number) {
    return this.request(`/expenses/${id}`, { method: 'DELETE' });
  }

  async getExpenseCategories() {
    return this.request<string[]>('/expenses/categories/list');
  }

  async getExpenseSummary() {
    return this.request<any>('/expenses/stats/summary');
  }

  // ============ PAYMENTS ============
  async getPayments(params?: { invoice_id?: number; page?: number; limit?: number }) {
    const query = new URLSearchParams(params as Record<string, string>);
    return this.request<{ data: any[]; total: number }>(`/payments?${query}`);
  }

  async getPayment(id: number) {
    return this.request<any>(`/payments/${id}`);
  }

  async createPayment(data: any) {
    return this.request<any>('/payments', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updatePayment(id: number, data: any) {
    return this.request<any>(`/payments/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deletePayment(id: number) {
    return this.request(`/payments/${id}`, { method: 'DELETE' });
  }

  async getUnmatchedPayments() {
    return this.request<any[]>('/payments/unmatched/list');
  }

  async getPaymentSummary() {
    return this.request<any>('/payments/stats/summary');
  }

  // ============ CUSTOMERS ============
  async getCustomers(params?: { search?: string; page?: number; limit?: number }) {
    const query = new URLSearchParams(params as Record<string, string>);
    return this.request<{ data: any[]; total: number }>(`/customers?${query}`);
  }

  async getCustomer(id: number) {
    return this.request<any>(`/customers/${id}`);
  }

  async createCustomer(data: any) {
    return this.request<any>('/customers', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateCustomer(id: number, data: any) {
    return this.request<any>(`/customers/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  async deleteCustomer(id: number) {
    return this.request(`/customers/${id}`, { method: 'DELETE' });
  }

  async getCustomerSummary() {
    return this.request<any>('/customers/stats/summary');
  }
}

export const api = new ApiClient();
