import React from 'react';
import { CheckCircle2, AlertTriangle, ShieldAlert } from 'lucide-react';
import type { PolicyDecisionType } from '../types/index.ts';

interface DecisionBadgeProps {
  decision?: PolicyDecisionType | null;
  reasons?: string[];
  showReasons?: boolean;
}

export const DecisionBadge: React.FC<DecisionBadgeProps> = ({
  decision,
  reasons = [],
  showReasons = false,
}) => {
  if (!decision) {
    return (
      <span className="badge badge-blue">
        <span>PENDING EVALUATION</span>
      </span>
    );
  }

  const config = {
    ALLOW: {
      badgeClass: 'badge badge-allow',
      icon: <CheckCircle2 size={13} />,
      label: 'ALLOW',
      description: 'Permitted automatically within deterministic bounds',
    },
    ESCALATE: {
      badgeClass: 'badge badge-escalate',
      icon: <AlertTriangle size={13} />,
      label: 'ESCALATE',
      description: 'Requires explicit human authorization before signing',
    },
    BLOCK: {
      badgeClass: 'badge badge-block',
      icon: <ShieldAlert size={13} />,
      label: 'BLOCK',
      description: 'Violates security policy; forbidden from signing',
    },
  }[decision];

  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', gap: '4px' }}>
      <span className={config.badgeClass} title={config.description}>
        {config.icon}
        <span>{config.label}</span>
      </span>
      {showReasons && reasons.length > 0 && (
        <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '2px' }}>
          {reasons.map((r, i) => (
            <span
              key={i}
              style={{
                display: 'inline-block',
                background: 'rgba(255, 255, 255, 0.05)',
                padding: '2px 6px',
                borderRadius: '4px',
                marginRight: '4px',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {r}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};
