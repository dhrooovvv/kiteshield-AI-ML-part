import { autonomyRequest, type AutonomyTask } from './autonomy.ts';

export interface CommerceCatalog {
  enabled: boolean;
  mode: string;
  product: { id: string; name: string; description: string; price_wei: string; currency: string };
  merchant: { name: string; recipient: string } | null;
  ready: boolean;
  reason: string | null;
  goal: string;
}
export interface PurchaseOrder {
  id: string;
  mode: string;
  state: string;
  reason: string | null;
  created_at: number;
  merchant: { name: string; recipient: string };
  product: CommerceCatalog['product'];
  quote: {
    digest: string; total_wei: string; recipient: string; currency: string;
    chain_id: number; expires_at: number;
    line_items: { name?: string; label?: string; amount_wei?: string; total_wei?: string }[];
  };
  invoice: { number: string; total_wei: string; status: string };
  task_id: string | null;
  task: AutonomyTask | null;
  events: { id: number; kind: string; detail: string }[];
  receipt: { tx_hash: string; explorer_url: string } | null;
  delivered: boolean;
  artifact: { name: string; content: string; mime_type: string } | null;
}
export const commerceRequest = <T>(path: string, body?: unknown) =>
  autonomyRequest<T>('/commerce' + path, 'proposer', body);
export async function commerceAvailable(): Promise<boolean> {
  try { return (await commerceRequest<CommerceCatalog>('/catalog')).enabled === true; }
  catch { return false; }
}
export function purchaseExplorer(order: PurchaseOrder): string | null {
  const hash = order.receipt?.tx_hash;
  return order.mode === 'SEPOLIA' && hash && /^0x[0-9a-fA-F]{64}$/.test(hash)
    ? `https://sepolia.etherscan.io/tx/${hash}` : null;
}
