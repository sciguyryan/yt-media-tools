# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover 0.30.x - Unreleased

- [feature] Define left-to-right `AND` and `OR` evaluation, SQL three-valued results and dominating-left short-circuit reachability as observable yt-sql language semantics.
- [test] Cover the complete Boolean truth table together with skipped and necessarily reachable right operands.
- [docs] Document Boolean evaluation order, UNKNOWN behaviour and the boundary between final truth and permission to suppress evaluation.
- [maintenance] Unify row and HAVING Boolean connectives behind one lazy three-valued evaluator while retaining surface-specific leaf evaluation.
- [test] Verify the shared Boolean contract across HAVING, relation-aware JOIN predicates and collection quantifiers, including quantifier early termination.
- [docs] Document the common predicate-evaluation contract and the distinct `ANY`/`ALL` reduction rules layered on top of it.

- [maintenance] Constrain Boolean optimisation explicitly by left-to-right evaluation reachability, keeping dominating-right constants from suppressing observable left operands.
- [test] Cover dominating-left reachability, dominating-right non-suppression and safe non-dominating right identities at the optimiser boundary.
- [docs] Document the distinction between Boolean truth provability and permission to suppress or reorder evaluation.

- [maintenance] Carry Boolean evaluation reachability into optimiser decisions and machine-readable explain data so skipped operands are reported explicitly rather than inferred from algebraic simplification.
- [test] Verify reachability effects survive optimiser-to-explain projection and diagnostic decision rendering.
- [docs] Document short-circuit planning and explainability as a distinction between truth, reachability and reordering permission.

- [test] Add adversarial nested Boolean coverage across ordinary predicates, HAVING, relation contexts and collection quantifiers, including reachable failures and unreachable branches.
- [test] Pin optimiser behaviour for nested volatile expressions so truth simplification cannot suppress an observable left operand.
- [docs] Record completion of the cross-surface Boolean conformance and adversarial coverage pass.
- [docs] Reconcile the completed short-circuit language decision, optimiser proof boundary and explain contract, including the final Markdown heading-hierarchy correction.
- [maintenance] Avoid per-row Boolean callback allocation while preserving the shared lazy short-circuit evaluator and identical observable semantics.

## Downloader 1.19.x - Unreleased

- [feature] Add `--remove-completed-rows` for annotated file-backed queues whose first whitespace-delimited field is the download target.
- [maintenance] Preserve the exact-line semantics of `--remove-completed-ids` while sharing archive reconciliation and queue reporting with annotated-row removal.
- [test] Add deterministic annotated-row parsing, atomic removal, archive reconciliation and command-planning coverage.
