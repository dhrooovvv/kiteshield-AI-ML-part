/**
 * KiteShield Wallet — Centralized Typed API Client
 *
 * Interacts with the backend via HTTP, handling authentication,
 * correlation IDs, typed errors, and response envelopes.
 */

import type {
  APIEnvelope,
  APIErrorDetails,
  AuditIntegrityVerification,
  AuditTrail,
  BackendHealth,
  EconomicCheckPayload,
  EconomicCheckResult,
  PendingApproval,
  PromptReviewEvent,
  Policy,
  PolicyCreatePayload,
  PolicyUpdatePayload,
  Proposal,
  ProposalListResponse,
  Transaction,
} from '../types/index.ts';
import type { PortfolioSnapshot } from '../portfolio.ts';

export class KiteShieldAPIError extends Error {
  public code: string;
  public status: number;
  public correlationId?: string;
  public details?: Record<string, unknown>;

  constructor(message: string, status: number, code: string, correlationId?: string, details?: Record<string, unknown>) {
    super(message);
    this.name = 'KiteShieldAPIError';
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
    this.details = details;
  }
}

export type CredentialRole = 'proposer' | 'approver' | 'policyAdmin' | 'demoAdmin';
export const credentialRoleLabels: Record<CredentialRole, string> = {
  proposer: 'Proposer', approver: 'Human approver', policyAdmin: 'Policy administrator',
  demoAdmin: 'Demo administrator (simulation only)',
};
const backendRoles: Record<CredentialRole, string> = {
  proposer: 'proposer', approver: 'human_approver', policyAdmin: 'policy_administrator',
  demoAdmin: 'demo_admin',
};
const emptyRoles: readonly CredentialRole[] = Object.freeze([]);

class APIClient {
  private apiKey: string;
  private roleKeys = { approver: '', policyAdmin: '', demoAdmin: '' };
  private baseUrl: string;
  private connectedRoles: readonly CredentialRole[] = emptyRoles;
  private credentialListeners = new Set<() => void>();
  private screeningListeners = new Set<() => void>();
  public subscribeScreeningEvents = (listener: () => void): (() => void) => {
    this.screeningListeners.add(listener);
    return () => { this.screeningListeners.delete(listener); };
  };
  public getConnectedRoles = (): readonly CredentialRole[] => this.connectedRoles;
  public getServerConnectedRoles = (): readonly CredentialRole[] => emptyRoles;
  public subscribeCredentials = (listener: () => void): (() => void) => {
    this.credentialListeners.add(listener);
    return () => { this.credentialListeners.delete(listener); };
  };
  private setVerified(role: CredentialRole, verified: boolean): void {
    const roles = (Object.keys(backendRoles) as CredentialRole[]).filter(
      (item) => item === role ? verified : this.connectedRoles.includes(item)
    );
    if (roles.join() === this.connectedRoles.join()) return;
    this.connectedRoles = Object.freeze(roles);
    this.credentialListeners.forEach((listener) => listener());
  }

  constructor() {
    // API credentials stay in memory only. VITE_* values are public build
    // configuration and browser storage is not a suitable secret store.
    this.apiKey = '';
    this.baseUrl = import.meta.env?.VITE_API_BASE_URL || '/api/v1';
  }

  public getApiKey(): string {
    return this.apiKey;
  }

  public setApiKey(key: string): void {
    this.apiKey = key.trim();
    this.setVerified('proposer', false);
  }

  public getRoleKey(role: CredentialRole): string {
    return role === 'proposer' ? this.apiKey : this.roleKeys[role];
  }

  public setRoleKey(role: CredentialRole, key: string): void {
    if (role === 'proposer') this.setApiKey(key);
    else {
      this.roleKeys[role] = key.trim();
      this.setVerified(role, false);
    }
  }

  private keyForAction(role: Exclude<CredentialRole, 'demoAdmin'>): string {
    return this.connectedRoles.includes('demoAdmin') ? this.roleKeys.demoAdmin : this.getRoleKey(role);
  }

  public async verifyAndSaveRoleKey(role: CredentialRole, key: string): Promise<void> {
    const candidate = key.trim();
    if (!candidate) {
      throw new KiteShieldAPIError('Enter the credential value, not its environment-variable name.', 401, 'MISSING_API_KEY');
    }
    const result = await this.request<unknown>('/security/identity', {
      method: 'GET', headers: { 'X-API-Key': candidate },
    });
    if (!result || typeof result !== 'object' || !('role' in result) ||
        !Object.values(backendRoles).includes(result.role as string)) {
      throw new KiteShieldAPIError('The backend returned an unexpected authentication response.', 502, 'INVALID_AUTH_RESPONSE');
    }
    if (result.role !== backendRoles[role]) {
      throw new KiteShieldAPIError('This credential belongs to a different role. Choose its matching role.', 403, 'CREDENTIAL_ROLE_MISMATCH');
    }
    this.setRoleKey(role, candidate);
    this.setVerified(role, true);
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-API-Key': this.keyForAction('proposer') || ((options.method ?? 'GET') === 'GET' && this.connectedRoles.length
        ? this.getRoleKey(this.connectedRoles[0]) : ''),
      ...(options.headers as Record<string, string>),
    };

    let response: Response;
    try {
      response = await fetch(url, {
        ...options,
        headers,
        cache: 'no-store',
        signal: options.signal ?? AbortSignal.timeout(60000),
      });
    } catch (networkErr: unknown) {
      const msg = networkErr instanceof Error ? networkErr.message : 'Network request failed';
      throw new KiteShieldAPIError(
        `Failed to connect to KiteShield backend at ${url}: ${msg}`,
        0,
        'NETWORK_ERROR'
      );
    }

    const contentType = response.headers.get('content-type') || '';
    let body: unknown;
    if (contentType.includes('application/json')) {
      try {
        body = await response.json();
      } catch {
        body = null;
      }
    } else {
      body = await response.text();
    }

    if (!response.ok) {
      if (response.status === 401) {
        for (const role of this.connectedRoles) {
          if (this.getRoleKey(role) === headers['X-API-Key']) this.setRoleKey(role, '');
        }
      }
      const errorData = body as APIErrorDetails | { detail?: unknown } | null;
      const structuredError =
        errorData && typeof errorData === 'object' && 'error' in errorData
          ? errorData.error
          : null;
      const fastApiDetail =
        errorData && typeof errorData === 'object' && 'detail' in errorData
          ? errorData.detail
          : null;
      const detailObject =
        fastApiDetail && typeof fastApiDetail === 'object' ? fastApiDetail : null;
      const code =
        structuredError?.code ||
        (detailObject && 'code' in detailObject && typeof detailObject.code === 'string'
          ? detailObject.code
          : `HTTP_${response.status}`);
      if (code === 'DEMO_ADMIN_SIMULATION_ONLY' && headers['X-API-Key'] === this.roleKeys.demoAdmin) {
        this.setRoleKey('demoAdmin', '');
      }
      const message =
        structuredError?.message ||
        (typeof fastApiDetail === 'string'
          ? fastApiDetail
          : detailObject && 'message' in detailObject && typeof detailObject.message === 'string'
            ? detailObject.message
            : response.statusText || 'Unknown API Error');
      const correlationId =
        structuredError?.correlation_id ||
        (detailObject && 'correlation_id' in detailObject && typeof detailObject.correlation_id === 'string'
          ? detailObject.correlation_id
          : response.headers.get('X-Correlation-ID') || undefined);
      const details =
        structuredError?.details ||
        (detailObject && 'details' in detailObject && typeof detailObject.details === 'object'
          ? (detailObject.details as Record<string, unknown>)
          : undefined);

      if (code === 'PROMPT_INJECTION_DETECTED' || code === 'PROMPT_SCREENING_REVIEW_REQUIRED') {
        this.screeningListeners.forEach((listener) => {
          // Notification failures must never turn a rejected request into success.
          try { listener(); } catch { /* Normal polling remains available. */ }
        });
      }
      throw new KiteShieldAPIError(message, response.status, code, correlationId, details);
    }

    // Return the unpacked data field from APIEnvelope<T> if present
    if (body && typeof body === 'object' && 'data' in body) {
      return (body as APIEnvelope<T>).data;
    }

    return body as T;
  }

  // ---- Health ----
  public async getPortfolio(signal?: AbortSignal): Promise<PortfolioSnapshot> {
    return this.request('/portfolio', { signal: signal
      ? AbortSignal.any([signal, AbortSignal.timeout(60000)]) : undefined });
  }
  public async checkHealth(): Promise<BackendHealth> {
    return this.request<BackendHealth>('/health');
  }

  // ---- Policies ----
  public async getActivePolicy(): Promise<Policy> {
    return this.request<Policy>('/policies/active');
  }

  public async listPolicies(): Promise<Policy[]> {
    return this.request<Policy[]>('/policies');
  }

  public async createPolicy(payload: PolicyCreatePayload): Promise<Policy> {
    return this.request<Policy>('/policies', {
      method: 'POST',
      headers: { 'X-API-Key': this.keyForAction('policyAdmin') },
      body: JSON.stringify(payload),
    });
  }

  public async updatePolicy(id: string, payload: PolicyUpdatePayload): Promise<Policy> {
    return this.request<Policy>(`/policies/${id}`, {
      method: 'PUT',
      headers: { 'X-API-Key': this.keyForAction('policyAdmin') },
      body: JSON.stringify(payload),
    });
  }

  // ---- Proposals ----
  public async listProposals(status?: string, limit = 50, offset = 0): Promise<ProposalListResponse> {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (status) params.append('status', status);
    return this.request<ProposalListResponse>(`/proposals?${params.toString()}`);
  }

  public async getProposal(id: string): Promise<Proposal> {
    return this.request<Proposal>(`/proposals/${id}`);
  }

  public async createDirectProposal(data: {
    prompt: string;
    recipient: string;
    amount_wei: string;
    chain_id?: number;
    asset_type?: string;
  }): Promise<Proposal> {
    return this.request<Proposal>('/proposals', {
      method: 'POST',
      body: JSON.stringify({
        prompt: data.prompt,
        recipient: data.recipient,
        amount_wei: data.amount_wei,
        chain_id: data.chain_id || 11155111,
        asset_type: data.asset_type || 'NATIVE_ETH',
      }),
    });
  }

  public async proposeWithAgent(prompt: string): Promise<Proposal> {
    return this.request<Proposal>('/proposals/agent', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    });
  }

  public async evaluateProposal(id: string): Promise<Proposal> {
    return this.request<Proposal>(`/proposals/${id}/evaluate`, {
      method: 'POST',
    });
  }

  public async signProposal(id: string): Promise<Proposal> {
    return this.request<Proposal>(`/proposals/${id}/sign`, {
      method: 'POST',
    });
  }

  // ---- Approvals ----
  public async listPendingApprovals(): Promise<PendingApproval[]> {
    return this.request<PendingApproval[]>('/approvals/pending');
  }

  public async decideApproval(
    approvalId: string,
    decision: 'APPROVE' | 'REJECT'
  ): Promise<PendingApproval> {
    return this.request<PendingApproval>(`/approvals/${approvalId}/decide`, {
      method: 'POST',
      headers: { 'X-API-Key': this.keyForAction('approver') },
      body: JSON.stringify({ decision }),
    });
  }

  // ---- Transactions ----
  public async checkEconomics(payload: EconomicCheckPayload, signal?: AbortSignal): Promise<EconomicCheckResult> {
    const result = await this.request<EconomicCheckResult>('/security/economic-check', {
      method: 'POST',
      body: JSON.stringify(payload),
      signal,
    });
    if (!result || result.advisory_only !== true || result.estimate_source !== 'CALLER_SUPPLIED'
      || typeof result.is_economically_viable !== 'boolean'
      || !/^\d+$/.test(result.gas_cost_wei) || typeof result.gas_cost_wei !== 'string'
      || typeof result.gas_cost_eth !== 'string' || !/^\d+(\.\d+)?$/.test(result.gas_cost_eth)
      || (result.gas_to_value_ratio !== null && (typeof result.gas_to_value_ratio !== 'string' || !/^\d+(\.\d+)?$/.test(result.gas_to_value_ratio)))
      || !Array.isArray(result.warnings) || !result.warnings.every((warning) => typeof warning === 'string')) {
      throw new KiteShieldAPIError('The fee check returned an invalid response. Please retry.', 502, 'INVALID_ECONOMIC_RESPONSE');
    }
    return result;
  }

  public async getTransaction(txId: string): Promise<Transaction> {
    return this.request<Transaction>(`/transactions/${txId}`);
  }

  // ---- Audit ----
  public async getScreeningCounts(): Promise<{
    blocked_count: number; screening_block_count: number; policy_block_count: number;
  }> {
    return this.request('/audit/screening-counts');
  }
  public async getAuditTrail(correlationId: string): Promise<AuditTrail> {
    return this.request<AuditTrail>(`/audit/${correlationId}`);
  }

  public async verifyAuditIntegrity(limit = 100): Promise<AuditIntegrityVerification> {
    return this.request<AuditIntegrityVerification>(`/audit/integrity/verify?limit=${limit}`);
  }

  public async listPromptScreeningReviews(limit = 50): Promise<PromptReviewEvent[]> {
    return this.request<PromptReviewEvent[]>(`/audit/prompt-reviews?limit=${limit}`);
  }
}

export const api = new APIClient();
