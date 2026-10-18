import type { Proposal, Transaction } from './types/index.ts';

// Refresh existing signed hashes only. This function can never sign or submit.
export async function refreshPaymentReceipts(
  proposals: Proposal[], readReceipt: (id: string) => Promise<Transaction>,
): Promise<{ proposals: Proposal[]; failed: boolean }> {
  let failed = false;
  const updated = await Promise.all(proposals.map(async (proposal) => {
    const transaction = proposal.transaction;
    if (transaction?.execution_mode !== 'sepolia' ||
        !['SIGNED', 'SUBMITTED'].includes(transaction.status)) return proposal;
    try {
      const refreshed = await readReceipt(transaction.id);
      return {
        ...proposal, transaction: refreshed,
        status: refreshed.status === 'CONFIRMED' ? 'CONFIRMED' as const
          : refreshed.status === 'FAILED' ? 'TX_FAILED' as const : proposal.status,
      };
    } catch {
      failed = true;
      return proposal;
    }
  }));
  return { proposals: updated, failed };
}
