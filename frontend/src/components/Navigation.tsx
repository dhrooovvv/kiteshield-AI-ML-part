import React from 'react';
import {
  LayoutDashboard,
  Send,
  UserCheck,
  ShieldCheck,
  History,
  Wallet,
  Repeat,
} from 'lucide-react';

export type NavTab = 'overview' | 'proposals' | 'approvals' | 'policies' | 'audit' | 'portfolio' | 'treasury';

interface NavigationProps {
  currentTab: NavTab;
  onTabChange: (tab: NavTab) => void;
  pendingApprovalsCount: number;
  promptReviewsCount: number;
  totalProposalsCount: number;
}

export const Navigation: React.FC<NavigationProps> = ({
  currentTab,
  onTabChange,
  pendingApprovalsCount,
  promptReviewsCount,
  totalProposalsCount,
}) => {
  const tabs = [
    {
      id: 'overview' as NavTab,
      label: 'Overview',
      icon: <LayoutDashboard size={18} />,
    },
    { id: 'portfolio' as NavTab, label: 'Portfolio', icon: <Wallet size={18} /> },
    { id: 'treasury' as NavTab, label: 'Treasury Autopilot', icon: <Repeat size={18} /> },
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
      badge: pendingApprovalsCount + promptReviewsCount > 0 ? pendingApprovalsCount + promptReviewsCount : undefined,
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
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div>
          <strong>KiteShield</strong>
        </div>
      </div>
      <nav className="sidebar-nav" aria-label="Primary navigation">
        {tabs.map((tab) => {
          const isActive = currentTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={`sidebar-link${isActive ? ' active' : ''}`}
              aria-current={isActive ? 'page' : undefined}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
              {tab.badge !== undefined && (
                <span
                  className="sidebar-badge"
                >
                  {tab.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>
    </aside>
  );
};
