export interface FundingRequest {
  id: string; address: string; mode: 'simulated' | 'sepolia';
  state: string; reason: string | null; chain_id: number;
  tx_hash: string | null; explorer_url: string | null;
  amount_wei: string | null; block_number: number | null; created_at: string;
}
export interface FundingStatus {
  wallets: { address: string; label: string }[];
  mode: 'simulated' | 'sepolia'; unavailable_reason: string | null;
  requests: FundingRequest[];
}
export type FundingPlan = FundingRequest | {
  state: 'WALLET_REQUIRED'; message: string; wallets: FundingStatus['wallets'];
};
export function fundingExplorer(request: FundingRequest): string | null {
  return request.mode === 'sepolia' && request.chain_id === 11155111 &&
    /^0x[0-9a-fA-F]{64}$/.test(request.tx_hash ?? '') &&
    ['SUBMITTED', 'CONFIRMED', 'REVERTED'].includes(request.state)
    ? `https://sepolia.etherscan.io/tx/${request.tx_hash}` : null;
}
export function fundingMessage(request: FundingRequest): string {
  return ({ PREPARED: 'Ready to request test ETH', REQUESTING: 'Request in progress · do not request again',
    SUBMITTED: 'Faucet transaction submitted · waiting for a receipt',
    CONFIRMED: 'Wallet funded · successful receipt recorded (not finality)',
    REVERTED: 'Faucet transaction reverted · wallet not funded',
    SIMULATED: 'Simulated only · no test ETH received',
    FAILED: 'Faucet request refused', UNCERTAIN: 'Delivery uncertain · do not request again',
  } as Record<string, string>)[request.state] ?? 'Funding status unavailable';
}
