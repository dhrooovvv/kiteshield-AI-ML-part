/**
 * KiteShield Wallet — Frontend Domain & API Types
 *
 * Strictly matches backend Pydantic schemas and OpenAPI response envelopes.
 */

export type ProposalStatus =
  | 'PROPOSED'
  | 'EVALUATING'
  | 'ALLOWED'
  | 'ESCALATED'
  | 'BLOCKED'
  | 'APPROVED'
  | 'REJECTED'
  | 'EXPIRED_APPROVAL'
  | 'AUTHORIZED'
  | 'SIGNING'
  | 'SIGNED'
  | 'SUBMITTED'
  | 'CONFIRMED'
  | 'FAILED'
  | 'SIGN_FAILED'
  | 'TX_FAILED';

export type PolicyDecisionType = 'ALLOW' | 'ESCALATE' | 'BLOCK';

export type AssetType = 'NATIVE_ETH';

export interface PolicyDecision {
  decision: PolicyDecisionType;
  reason_codes: string[];
  policy_version: number;
  evaluated_at: string;
}

export interface Approval {
  id: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'EXPIRED';
  action_digest: string;
  expires_at: string;
  decided_at?: string | null;
}

export interface Transaction {
  execution_outcome?: 'SIGNED' | 'SIMULATED' | 'UNCERTAIN' | 'SUBMITTED' | 'CONFIRMED' | 'REVERTED' | null;
  receipt?: Record<string, unknown> | null;
  explorer_url?: string | null;
  execution_mode?: 'simulated' | 'sepolia' | null;
  id: string;
  tx_hash?: string | null;
  status: 'SIGNING' | 'SIGNED' | 'SUBMITTED' | 'CONFIRMED' | 'FAILED';
  block_number?: number | null;
  gas_used?: number | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface Proposal {
  provenance?: 'DETERMINISTIC_MANDATE' | 'AGENT_OR_STRUCTURED';
  mandate_version?: number | null;
  auto_execution_enabled?: boolean;
  auto_execution_max_wei?: string;
  id: string;
  correlation_id: string;
  prompt: string;
  recipient: string;
  amount_wei: string;
  amount_eth: string;
  chain_id: number;
  asset_type: string;
  status: ProposalStatus;
  created_at: string;
  updated_at: string;
  policy_decision?: PolicyDecision | null;
  approval?: Approval | null;
  transaction?: Transaction | null;
}

export interface ProposalListResponse {
  proposals: Proposal[];
  total: number;
}

export interface Policy {
  id: string;
  version: number;
  max_amount_wei: string;
  daily_limit_wei: string | null;
  allowed_recipients: string[] | null;
  blocked_recipients: string[] | null;
  escalation_threshold_wei: string | null;
  is_active: boolean;
  created_at: string;
}

export interface PolicyCreatePayload {
  max_amount_wei: string;
  daily_limit_wei?: string | null;
  allowed_recipients?: string[] | null;
  blocked_recipients?: string[] | null;
  escalation_threshold_wei?: string | null;
}

export interface PolicyUpdatePayload {
  max_amount_wei?: string | null;
  daily_limit_wei?: string | null;
  allowed_recipients?: string[] | null;
  blocked_recipients?: string[] | null;
  escalation_threshold_wei?: string | null;
}

export interface PendingApproval {
  id: string;
  proposal_id: string;
  action_digest: string;
  status: string;
  expires_at: string;
  approved_by: string | null;
  decided_at: string | null;
  created_at: string;
  proposal?: {
    prompt: string;
    recipient: string;
    amount_wei: string;
    amount_eth: string;
    chain_id: number;
  };
}

export interface PromptReviewEvent {
  id: string;
  correlation_id: string;
  event_type: 'PROMPT_SCREENING_REVIEW_REQUIRED';
  status: 'REVIEW_REQUIRED';
  review_type: 'PROMPT_SCREENING';
  reason_code: string | null;
  prompt_digest: string | null;
  created_at: string;
}

export interface ApprovalDecisionPayload {
  decision: 'APPROVE' | 'REJECT';
  approved_by: string;
}

export interface AuditEvent {
  id: string;
  correlation_id: string;
  event_type: string;
  actor: string;
  details: Record<string, unknown>;
  policy_version: number | null;
  previous_hash: string | null;
  event_hash: string;
  created_at: string;
}

export interface AuditTrail {
  correlation_id: string;
  events: AuditEvent[];
  chain_valid: boolean;
}

export interface AuditIntegrityVerification {
  is_valid: boolean;
  errors: string[];
  checked_limit: number;
}

export interface BackendHealth {
  execution_mode?: 'simulated' | 'sepolia';
  verified_chain_id?: number | null;
  verified_block_number?: number | null;
  rpc_verified_at?: string | null;
  status: string;
  service: string;
  version: string;
}

export interface APIEnvelope<T> {
  data: T;
  meta: {
    correlation_id?: string;
    total?: number;
    [key: string]: unknown;
  };
}

export interface EconomicCheckPayload {
  value_wei: string;
  estimated_gas: number;
  gas_price_gwei: string;
  max_gas_price_gwei: string;
}

export interface EconomicCheckResult extends EconomicCheckPayload {
  advisory_only: true;
  estimate_source: 'CALLER_SUPPLIED';
  is_economically_viable: boolean;
  gas_cost_wei: string;
  gas_cost_eth: string;
  gas_to_value_ratio: string | null;
  warnings: string[];
}

export interface APIErrorDetails {
  error: {
    code: string;
    message: string;
    correlation_id?: string;
    details?: Record<string, unknown>;
  };
}
