/** Exact decimal strings only. Never route payment amounts through Number. */
export function ethToWei(value: string): string {
  if (!/^(?:\d+|\d*\.\d{1,18})$/.test(value)) {
    throw new Error('Enter a positive ETH amount with at most 18 decimal places.');
  }
  const [whole, fraction = ''] = value.split('.');
  const wei = BigInt(whole || '0') * 10n ** 18n + BigInt(fraction.padEnd(18, '0'));
  if (wei <= 0n || wei > 10n ** 24n) throw new Error('Amount is outside the supported range.');
  return wei.toString();
}

export function weiToEth(value: string): string {
  if (!/^\d+$/.test(value)) throw new Error('Invalid wei amount.');
  const wei = BigInt(value);
  const fraction = (wei % (10n ** 18n)).toString().padStart(18, '0').replace(/0+$/, '');
  return (wei / (10n ** 18n)).toString() + (fraction ? '.' + fraction : '');
}
