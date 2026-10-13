import React from 'react';
import type { ProposalStatus } from '../types/index.ts';

interface StatusBadgeProps {
  status: ProposalStatus;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const getBadgeStyle = (): { className: string; label: string } => {
    switch (status) {
      case 'PROPOSED':
        return { className: 'badge badge-blue', label: 'PROPOSED' };
      case 'EVALUATING':
        return { className: 'badge badge-purple', label: 'EVALUATING' };
      case 'ALLOWED':
        return { className: 'badge badge-allow', label: 'ALLOWED' };
      case 'ESCALATED':
        return { className: 'badge badge-escalate', label: 'ESCALATED' };
      case 'BLOCKED':
        return { className: 'badge badge-block', label: 'BLOCKED' };
      case 'APPROVED':
        return { className: 'badge badge-allow', label: 'APPROVED' };
      case 'REJECTED':
        return { className: 'badge badge-block', label: 'REJECTED' };
      case 'EXPIRED_APPROVAL':
        return { className: 'badge badge-block', label: 'EXPIRED' };
      case 'SIGNING':
        return { className: 'badge badge-purple', label: 'SIGNING' };
      case 'SIGNED':
        return { className: 'badge badge-purple', label: 'SIGNED' };
      case 'SUBMITTED':
        return { className: 'badge badge-blue', label: 'SUBMITTED' };
      case 'CONFIRMED':
        return { className: 'badge badge-allow', label: 'CONFIRMED' };
      case 'FAILED':
      case 'SIGN_FAILED':
      case 'TX_FAILED':
        return { className: 'badge badge-block', label: 'FAILED' };
      default:
        return { className: 'badge badge-blue', label: status };
    }
  };

  const { className, label } = getBadgeStyle();
  return <span className={className}>{label}</span>;
};
