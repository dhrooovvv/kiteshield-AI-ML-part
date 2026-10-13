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
  PendingApproval,
  Policy,
  PolicyCreatePayload,
  PolicyUpdatePayload,
  Proposal,
  ProposalListResponse,
  Transaction,
} from '../types/index.ts';

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

class APIClient {
  private apiKey: string;
  private baseUrl: string;

  constructor() {
    this.apiKey = localStorage.getItem('kiteshield_api_key') || import.meta.env.VITE_API_KEY || '';
    this.baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1';
  }

  public getApiKey(): string {
    return this.apiKey;
  }

  public setApiKey(key: string): void {
    this.apiKey = key.trim();
    localStorage.setItem('kiteshield_api_key', this.apiKey);
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-API-Key': this.apiKey,
      ...(options.headers as Record<string, string>),
    };

    let response: Response;
    try {
      response = await fetch(url, {
        ...options,
        headers,
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
      const errorData = body as APIErrorDetails | null;
      const code = errorData?.error?.code || `HTTP_${response.status}`;
      const message = errorData?.error?.message || response.statusText || 'Unknown API Error';
      const correlationId = errorData?.error?.correlation_id || response.headers.get('X-Correlation-ID') || undefined;
      const details = errorData?.error?.details;

      throw new KiteShieldAPIError(message, response.status, code, correlationId, details);
    }

    // Return the unpacked data field from APIEnvelope<T> if present
    if (body && typeof body === 'object' && 'data' in body) {
      return (body as APIEnvelope<T>).data;
    }

    return body as T;
  }

  // ---- Health ----
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
      body: JSON.stringify(payload),
    });
  }

  public async updatePolicy(id: string, payload: PolicyUpdatePayload): Promise<Policy> {
    return this.request<Policy>(`/policies/${id}`, {
      method: 'PUT',
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
    decision: 'APPROVE' | 'REJECT',
    approvedBy = 'user:human_operator'
  ): Promise<PendingApproval> {
    return this.request<PendingApproval>(`/approvals/${approvalId}/decide`, {
      method: 'POST',
      body: JSON.stringify({ decision, approved_by: approvedBy }),
    });
  }

  // ---- Transactions ----
  public async getTransaction(txId: string): Promise<Transaction> {
    return this.request<Transaction>(`/transactions/${txId}`);
  }

  // ---- Audit ----
  public async getAuditTrail(correlationId: string): Promise<AuditTrail> {
    return this.request<AuditTrail>(`/audit/${correlationId}`);
  }

  public async verifyAuditIntegrity(limit = 100): Promise<AuditIntegrityVerification> {
    return this.request<AuditIntegrityVerification>(`/audit/integrity/verify?limit=${limit}`);
  }
}

export const api = new APIClient();
