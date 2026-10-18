export interface PortfolioSnapshot {
  mode: 'simulated' | 'sepolia';
  network: {
    status: 'available' | 'unavailable'; message?: string; reason?: string;
    chain_id?: number; block_number?: number; block_timestamp?: string;
    pending_nonce: number | null; allocation_basis?: string; valuation_notice?: string;
    holdings: { asset: string; address: string; role: string; balance: string;
      balance_raw: string; decimals: number;
      token_address: string | null; address_url: string; share_percent: string | null }[];
  };
  budget: {
    status: string; period: string; date: string; policy_version: number | null;
    daily_limit_eth: string | null; spent_today_eth: string; pending_eth: string;
    remaining_eth: string | null; spent_percent: string | null; pending_percent: string | null;
    auto_execute_enabled: boolean; autonomous_cap_eth: string;
    escalation_threshold_eth: string | null; absolute_max_eth: string | null;
  };
  recent_payments: { proposal_id: string; amount_eth: string; recipient: string;
    status: string; lifecycle_status: string; execution_outcome: string | null;
    tx_hash: string | null; explorer_url: string | null; created_at: string }[];
}

export interface PortfolioReadState {
  data: PortfolioSnapshot | null;
  error: string | null;
  refreshing: boolean;
  loadedAt: number | null;
}

export const initialPortfolioRead: PortfolioReadState = {
  data: null, error: null, refreshing: true, loadedAt: null,
};

export function portfolioReadReducer(state: PortfolioReadState, action:
  | { type: 'start' }
  | { type: 'success'; data: PortfolioSnapshot; at: number }
  | { type: 'failure'; message: string }): PortfolioReadState {
  if (action.type === 'start') return { ...state, refreshing: true, error: null };
  if (action.type === 'success') return {
    data: action.data, loadedAt: action.at, error: null, refreshing: false,
  };
  // Never leave a failed RPC/auth read looking like a current verified balance.
  return { data: null, loadedAt: null, refreshing: false, error: action.message };
}
