export interface MandateDraftResult {
  status: 'draft' | 'clarification' | 'refused' | 'invalid' | 'could_not_interpret';
  source: 'parser' | 'llm' | 'none'; resolved_recipient: string | null;
  draft: {
    target_balance_eth: string | null; recipient_alias: string | null;
    max_actions_per_day: number | null; sweep_maximum_eth: string | null;
    minimum_excess_eth: string | null; cooldown_seconds: number | null;
    freshness_seconds: number | null; unresolved_questions: string[];
  } | null;
  validation: string[]; questions: string[]; warnings: string[];
}

/** Apply only a successful draft to existing fields. This function makes no API calls. */
export function applyMandateDraft(form: HTMLFormElement, result: MandateDraftResult) {
  if (result.status !== 'draft' || !result.draft || !result.resolved_recipient) return;
  const d = result.draft;
  const fields: Record<string, string | number | null> = {
    recipient: result.resolved_recipient, target: d.target_balance_eth,
    daily: d.max_actions_per_day, maximum: d.sweep_maximum_eth,
    minimum: d.minimum_excess_eth, cooldown: d.cooldown_seconds,
    freshness: d.freshness_seconds,
  };
  for (const [key, value] of Object.entries(fields)) {
    const input = form.elements.namedItem(key);
    if (input instanceof HTMLInputElement) input.value = value === null ? '' : String(value);
  }
}
