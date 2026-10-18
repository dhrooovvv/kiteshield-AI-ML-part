import { useEffect, useId, useRef, useState } from 'react';
import { Check, ChevronDown, ListFilter } from 'lucide-react';
import { proposalFilters } from '../proposalFilters.ts';
import type { ProposalFilter } from '../proposalFilters.ts';

export function ProposalStatusFilter({ value, onChange }: {
  value: ProposalFilter;
  onChange: (value: ProposalFilter) => void;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const selected = proposalFilters.findIndex(option => option.value === value);

  useEffect(() => {
    if (!open) return;
    list.current?.focus();
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', dismiss);
    return () => document.removeEventListener('pointerdown', dismiss);
  }, [open]);

  const choose = (index: number) => {
    onChange(proposalFilters[index].value);
    setOpen(false);
    trigger.current?.focus();
  };

  return (
    <div className="proposals-status-filter" ref={root}
      onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}>
      <button className="proposals-filter-trigger" ref={trigger} type="button"
        aria-label={`Filter proposals by status: ${proposalFilters[selected].label}`}
        aria-haspopup="listbox" aria-expanded={open} aria-controls={`${id}-options`}
        onClick={() => { setActive(selected); setOpen(!open); }}
        onKeyDown={event => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            setActive(selected);
            setOpen(true);
          }
        }}>
        <ListFilter size={16} aria-hidden="true" />
        <span>{proposalFilters[selected].label}</span>
        <ChevronDown size={15} className={open ? 'filter-chevron-open' : ''} aria-hidden="true" />
      </button>
      {open && <div className="proposals-filter-menu" id={`${id}-options`} ref={list}
        role="listbox" aria-label="Proposal status" tabIndex={0}
        aria-activedescendant={`${id}-option-${active}`}
        onKeyDown={event => {
          const key = event.key;
          if (['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', ' ', 'Escape'].includes(key)) {
            event.preventDefault();
            if (key === 'ArrowDown') setActive((active + 1) % proposalFilters.length);
            if (key === 'ArrowUp') setActive((active + proposalFilters.length - 1) % proposalFilters.length);
            if (key === 'Home') setActive(0);
            if (key === 'End') setActive(proposalFilters.length - 1);
            if (key === 'Enter' || key === ' ') choose(active);
            if (key === 'Escape') { setOpen(false); trigger.current?.focus(); }
          } else if (key === 'Tab') {
            setOpen(false);
            trigger.current?.focus();
          } else if (key.length === 1) {
            const index = proposalFilters.findIndex(option => option.label.toLowerCase().startsWith(key.toLowerCase()));
            if (index >= 0) setActive(index);
          }
        }}>
        {proposalFilters.map((option, index) => (
          <div key={option.value} id={`${id}-option-${index}`} role="option"
            aria-selected={value === option.value}
            className={`proposals-filter-option${active === index ? ' is-active' : ''}`}
            onPointerMove={() => setActive(index)} onClick={() => choose(index)}>
            <span>{option.label}</span>
            {value === option.value && <Check size={16} aria-hidden="true" />}
          </div>
        ))}
      </div>}
    </div>
  );
}
