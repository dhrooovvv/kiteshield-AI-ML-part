# Human Approvals design update

Adapted the previously inspected Figma references to the existing dashboard: one flat white workspace, compact divided rows, restrained status colour, and expandable references instead of repeated cards. Google Sans Flex is retained.

Changed `frontend/src/views/ApprovalsView.tsx`, scoped styles in `frontend/src/index.css`, and the approvals-only timestamp visibility in `frontend/src/App.tsx`. Added `frontend/tests/approvalsDesign.test.ts`.

Transaction approval and informational security-hold sections remain distinct. Existing decision and audit callbacks are preserved. Security holds have no approval, signing, or execution action. No backend or payment behaviour changed.

Validation: frontend tests 44 passed; lint passed; TypeScript and Vite production build passed; git diff --check passed. SSR tests cover separate queues, exact details, available actions, errors, loading, and empty states. Test runs emitted existing Vite websocket port-in-use warnings without failures. Browser visual verification was unavailable because browser automation is disabled; responsive styles have not been visually verified.
