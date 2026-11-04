import { Inbox, Layers, Repeat, Wallet } from 'lucide-react';

export type NavTab = 'overview' | 'proposals' | 'approvals' | 'policies' | 'audit' | 'portfolio' | 'treasury' | 'invoices' | 'autonomy';

const reviewTabs = [
  { id: 'approvals', label: 'Human Approvals' },
  { id: 'proposals', label: 'Proposals' },
  { id: 'policies', label: 'Policy Engine' },
  { id: 'audit', label: 'Audit Explorer' },
] satisfies { id: NavTab; label: string }[];

const workflowTabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'treasury', label: 'Treasury Autopilot' },
  { id: 'invoices', label: 'Accounts Payable' },
] satisfies { id: NavTab; label: string }[];

function workspaceSection(tab: NavTab) {
  if (reviewTabs.some(item => item.id === tab)) return 'review';
  if (workflowTabs.some(item => item.id === tab)) return 'workflows';
  return tab;
}

interface NavigationProps {
  autonomyEnabled?: boolean;
  currentTab: NavTab;
  onTabChange: (tab: NavTab) => void;
  pendingApprovalsCount: number;
  promptReviewsCount: number;
}

export function Navigation({
  autonomyEnabled, currentTab, onTabChange, pendingApprovalsCount, promptReviewsCount,
}: NavigationProps) {
  const section = workspaceSection(currentTab);
  const attention = pendingApprovalsCount + promptReviewsCount;
  const tabs = [
    { section: 'workflows', id: 'overview' as const, label: 'Workflows', icon: Layers },
    ...(autonomyEnabled ? [{ section: 'autonomy', id: 'autonomy' as const, label: 'Agent', icon: Repeat }] : []),
    { section: 'portfolio', id: 'portfolio' as const, label: 'Wallet', icon: Wallet },
    { section: 'review', id: 'approvals' as const, label: 'Review', icon: Inbox, badge: attention },
  ];

  return <aside className="sidebar">
    <div className="sidebar-brand"><strong>KiteShield</strong></div>
    <nav className="sidebar-nav" aria-label="Primary navigation">
      {tabs.map(({ section: key, id, label, icon: Icon, badge }) => (
        <button key={key} onClick={() => onTabChange(id)}
          className={`sidebar-link${section === key ? ' active' : ''}`}
          aria-current={section === key ? 'page' : undefined}>
          <Icon size={18} aria-hidden="true" />
          <span>{label}</span>
          {!!badge && <span className="sidebar-badge" aria-label={`${badge} items need review`}>{badge}</span>}
        </button>
      ))}
    </nav>
  </aside>;
}

export function WorkspaceNavigation({ currentTab, onTabChange }: Pick<NavigationProps, 'currentTab' | 'onTabChange'>) {
  const section = workspaceSection(currentTab);
  const tabs = section === 'review' ? reviewTabs : section === 'workflows' ? workflowTabs : null;
  if (!tabs) return null;

  return <nav className="workspace-subnav" aria-label={section === 'review' ? 'Review tools' : 'Workflows'}>
    {tabs.map(tab => <button key={tab.id} className="btn btn-outline"
      aria-current={currentTab === tab.id ? 'page' : undefined}
      onClick={() => onTabChange(tab.id)}>{tab.label}</button>)}
  </nav>;
}
