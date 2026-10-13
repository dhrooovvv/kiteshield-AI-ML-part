import React from 'react';
import {
  LayoutDashboard,
  Send,
  UserCheck,
  ShieldCheck,
  History,
} from 'lucide-react';

export type NavTab = 'overview' | 'proposals' | 'approvals' | 'policies' | 'audit';

interface NavigationProps {
  currentTab: NavTab;
  onTabChange: (tab: NavTab) => void;
  pendingApprovalsCount: number;
  totalProposalsCount: number;
}

export const Navigation: React.FC<NavigationProps> = ({
  currentTab,
  onTabChange,
  pendingApprovalsCount,
  totalProposalsCount,
}) => {
  const tabs = [
    {
      id: 'overview' as NavTab,
      label: 'Overview',
      icon: <LayoutDashboard size={18} />,
    },
    {
      id: 'proposals' as NavTab,
      label: 'Proposals',
      icon: <Send size={18} />,
      badge: totalProposalsCount > 0 ? totalProposalsCount : undefined,
    },
    {
      id: 'approvals' as NavTab,
      label: 'Human Approvals',
      icon: <UserCheck size={18} />,
      badge: pendingApprovalsCount > 0 ? pendingApprovalsCount : undefined,
      badgeColor: 'var(--color-amber)',
    },
    {
      id: 'policies' as NavTab,
      label: 'Policy Engine',
      icon: <ShieldCheck size={18} />,
    },
    {
      id: 'audit' as NavTab,
      label: 'Audit Explorer',
      icon: <History size={18} />,
    },
  ];

  return (
    <nav
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        borderBottom: '1px solid var(--border-light)',
        padding: '0 24px',
        background: 'rgba(10, 16, 29, 0.4)',
        overflowX: 'auto',
      }}
    >
      <div style={{ maxWidth: '1440px', width: '100%', margin: '0 auto', display: 'flex', gap: '8px' }}>
        {tabs.map((tab) => {
          const isActive = currentTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '14px 16px',
                background: 'transparent',
                border: 'none',
                borderBottom: `2px solid ${isActive ? 'var(--color-cyan)' : 'transparent'}`,
                color: isActive ? '#fff' : 'var(--text-muted)',
                fontWeight: isActive ? 600 : 500,
                fontSize: '0.9rem',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
                whiteSpace: 'nowrap',
                fontFamily: 'var(--font-main)',
              }}
            >
              <span style={{ color: isActive ? 'var(--color-cyan)' : 'inherit' }}>{tab.icon}</span>
              <span>{tab.label}</span>
              {tab.badge !== undefined && (
                <span
                  style={{
                    fontSize: '0.7rem',
                    fontWeight: 700,
                    padding: '2px 7px',
                    borderRadius: '10px',
                    background: tab.badgeColor
                      ? 'rgba(245, 158, 11, 0.2)'
                      : 'rgba(255, 255, 255, 0.1)',
                    color: tab.badgeColor || '#fff',
                    border: tab.badgeColor ? '1px solid rgba(245, 158, 11, 0.4)' : 'none',
                  }}
                >
                  {tab.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
};
