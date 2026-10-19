# Treasury dashboard layout

UI-only refinement following the existing Portfolio/Overview language. Two cards
on desktop: a white mandate configuration/control panel and a dark forest-green
sweep eligibility/execution panel. Narrow layouts stack in the same DOM order.

Follow-up density refinement: activity is now the third card in the same grid,
directly below configuration while eligibility spans the right column. It no
longer waits below the taller card or stretches full-width. Activity rows use
compact metadata; payment cards remain accessible inside Payment details rather
than being permanently expanded. Mobile stacks configuration, eligibility, then
activity, matching DOM/focus order. No fixed-height nested scrolling introduced.

Overview-style integration: all three sections now sit inside one rounded outer
workspace with no gutters or separate inner card borders/radii. Configuration and
activity share the white left column with a thin divider; eligibility is a continuous
dark-green right rail spanning both rows. On narrow screens, the sections stack
inside that same parent panel. Existing colours, values and controls are preserved.
Existing Google Sans Flex, flat surfaces and readable white-on-green text retained.

Eligibility is separate from payment evidence: an eligible amount is explicitly
not executed, active monitoring is not confirmation, stale snapshots cannot display
a fresh eligible sweep, and simulated executions never gain explorer links. The
latest execution links to existing evidence; existing proposal/receipt cards remain.

Only the latest activity appears initially. Earlier activities and payment details
open separate centered native modal dialogs with a bounded, scrollable body,
Escape/Close dismissal and focus restoration. Existing audit/detail actions close
the history dialog before opening their own view. The smaller left section avoids
forcing unnecessary height onto the green rail; history no longer expands inline.
The duplicate global last-updated line is hidden on this tab. Existing mutations,
role checks, version-pinned confirmation, API polling and execution behaviour are
unchanged. No backend/configuration changes or live actions in this UI task.

Files: `frontend/src/views/TreasuryView.tsx`, `frontend/src/index.css`,
`frontend/src/App.tsx`, `frontend/tests/treasury.test.ts` and this report.

Validation: 49 frontend tests passed; lint, TypeScript, Vite production build and
git diff --check passed. Impeccable layout detector returned no findings on the
changed view/CSS. Browser visual verification remains unavailable; source/SSR
tests do not substitute for real-browser responsive/keyboard interaction checks.
The latest activity regression checks that exactly one row is visible on the
dashboard and all earlier rows are retained for the dialog.
