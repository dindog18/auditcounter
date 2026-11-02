# Case investigation, review and resolution

Existing AP/AR reconciliation cases now support a shared human investigation workflow in the existing `discrepancies` app. No accounting system, duplicate finding model, authentication, ERP write-back, recovery ledger or frontend framework was added.

## Three separate states

- **Reconciliation:** computed by the existing matching/financial evaluator.
- **Finding:** automatically open or cleared according to deterministic rules.
- **Investigation/review:** human workflow status and finding review decisions.

Confirming or dismissing a finding changes only its human review fields. Resolving or dismissing an investigation changes only its workflow and activity history. Human decisions never assign reconciliation status, clear detected findings or rewrite financial source values. The UI continues showing open financial differences even when a business exception closes the investigation. Financial exposure displays existing backend components, not an invented recovered-money balance.

## Migration and compatibility

Apply the new migration before using the updated application:

```sh
python auditcounter_django/manage.py migrate
```

`discrepancies/0002_discrepancyfinding_review_basis_and_more.py` adds:

- `CaseInvestigation`: nullable AP/AR one-to-one case relationships, workflow status, plain-text responsible department and next action, latest resolution category/notes/evidence/basis, renewed-review flag/reason, opened/updated/closed dates.
- `CaseActivity`: protected investigation FK, optional protected finding FK, event type, previous/new workflow status, notes, manually supplied actor label, immutable decision/evidence details and creation date.
- Finding review fields: `review_decision`, `review_notes`, `reviewed_at`, `review_basis`.
- Database constraints for exactly one AP/AR case, one investigation per transaction and consistent active/closed status timestamps.

Existing findings default to `unreviewed`; no investigations are opened automatically. Existing financial records, findings and evidence remain intact. The existing flat `discrepancies.services` module was converted to a package: previous public helpers remain in `services/__init__.py`, preserving imports, callers and test patch paths.

Migrations were applied and tested on disposable SQLite/PostgreSQL databases. The existing workspace database was not migrated automatically.

## Workflow states

| Current | Allowed next operation |
| --- | --- |
| `needs_review` | Update to `investigating`, or documented dismissal |
| `investigating` | Update to `waiting`, or documented resolution/dismissal |
| `waiting` | Update to `investigating` |
| `resolved` | Explicit reopening to `needs_review`, with reason |
| `dismissed` | Explicit reopening to `needs_review`, with reason |

Routing fields may be updated while active. Closed investigations must be reopened before changing workflow or reviewing findings. Notes can be appended while closed for additional context. Status updates cannot bypass closure validation. Repeated start requests retrieve the same investigation without adding another opening event; they do not reopen it.

## Finding reviews

Decisions are `unreviewed`, `confirmed`, `dismissed`, and `needs_more_evidence`. A dismissed finding requires a written explanation. Every explicit review appends activity with its prior/new decision, original calculated values, finding identity and evidence IDs. Current review fields are separate from automatically synchronized finding fields.

If automatic values or evidence change after a review, the current decision is preserved but displayed as stale. A new review is needed before accepting an open finding as part of closure. Reconciliation reruns with unchanged business evidence preserve reviews and history without making them stale simply because detection timestamps changed.

## Resolution policy

Every closure requires a type and written explanation. Supported types are:

- `source_correction_verified`
- `corrective_document_verified`
- `business_exception_accepted`
- `false_positive`
- `other`

Closure evaluates current source evidence read-only and rejects findings that have not been synchronized to that evaluation. Correction-based outcomes require reconciliation to be `matched`, no open findings, and at least one valid current evidence/document reference. Historical snapshots whose source values, linkage or detected/cleared context no longer match are rejected as correction proof.

Other outcomes require current terminal reviews (`confirmed` or `dismissed`) of every open finding. False-positive outcomes require those open findings to be dismissed with explanations. These are validation rules for documented outcomes, not an approval hierarchy.

References can cite saved `FindingEvidence` IDs or linked PO/DR/SI records, optionally specific lines. Cross-case finding/evidence references, unlinked documents, inconsistent parties/currencies, invalid line ownership and duplicate references are rejected. Resolution activity captures selected observations and the finding/review state at closure; later source changes cannot rewrite that record.

Reopening preserves the investigation ID and previous resolution fields. An immutable reopening event also captures the prior resolution and closure time. A subsequent resolution becomes the current recorded outcome while earlier resolution events remain in history.

When reconciliation synchronization detects changed evidence after closure, it flags **Renewed review required** and appends one system activity. The closed status and recorded outcome remain unchanged until a human explicitly reopens. Unchanged reruns do not repeatedly append that flag. No credit, refund, payment or recovered-revenue entry is created.

## API

The existing POST-only, CSRF-protected routes serve both modules:

```text
/accounts-payable/api/<action>/<case_id>/
/accounts-receivable/api/<action>/<case_id>/
```

| Action | Fields besides `revision` and optional `actor_label` |
| --- | --- |
| `investigation-start` | None |
| `investigation-update` | `workflow_status`, `responsible_department`, `next_action`, optional change `notes` |
| `investigation-note` | Required `notes` |
| `finding-review` | `finding_id`, `decision`, `notes` (required for dismissal) |
| `investigation-resolve` | `workflow_status` (`resolved`/`dismissed`), `resolution_type`, `resolution_notes`, optional `evidence_ids`, `document_references` |
| `investigation-reopen` | Required `reason` |

Use the case's serialized `investigationRevision` token for writes. Unsupported fields and invalid bodies are rejected. Changes to investigation state, reviews, activities, case scope or underlying evidence invalidate stale writes with HTTP 409. Successful actions return investigation `id` and `case_id`; the frontend reloads authoritative state. Start is idempotent retrieval if an investigation already exists, including repeated requests with an older token, because retrieval performs no update.

Example closure:

```json
{
  "revision": "investigationRevision from workspace state",
  "workflow_status": "resolved",
  "resolution_type": "corrective_document_verified",
  "resolution_notes": "Verified the additional accepted receipt and all invoice allocations.",
  "document_references": [
    {"kind": "delivery_receipt", "record_id": 12}
  ],
  "evidence_ids": [],
  "actor_label": "Warehouse desk"
}
```

Document kinds are `purchase_order`, `delivery_receipt`, and `sales_invoice`. A `line_id` may additionally identify a line belonging to the selected document. Actor labels are optional and manually supplied; they are never verified identities.

Writes use atomic transactions, account/case/investigation row locks and revision checks. Correction verification also locks source evidence in the existing matching lock order. An interrupted activity append rolls back the associated review/workflow update.

## History preservation

Activities have no edit or delete API. Model saves reject changes to existing activity rows; queryset update/delete/bulk-update operations are blocked, and bulk inserts validate same-case finding ownership. Ownership checks read actual database relationships rather than trusting cached related objects. Protected FKs prevent normal parent deletion from silently removing history.

Each review and closure captures the values/decisions/evidence context needed to understand that step later. Opening, routing/status changes, notes, reviews, resolutions, reopenings and renewed-review flags remain in chronological history. This is application-enforced append-only history, not a tamper-proof database administration or verified-identity system.

## Frontend

The existing reconciliation detail page now contains:

1. **Investigation Overview:** workflow status, department, next action, open findings, backend financial-difference components, dates and renewed-review warning. Includes start, status/routing update, notes, documented closure and reopening forms.
2. **Findings Review:** existing findings and evidence, current human decision, review reason/date, stale-review warning and review controls. History links point back to individual finding anchors.
3. **Investigation History:** chronological immutable events, unverified actor labels, explanations, status transitions and expandable decision/evidence snapshots.

Existing matching, source-document links and recalculation controls remain. The matched-count caption now accurately says allocations rather than invoice lines when partial deliveries create multiple rows. Actual case currency is used throughout. No new navigation or frontend application was created.

## Exact file/function inventory for this milestone

| File | Change |
| --- | --- |
| `auditcounter_django/discrepancies/models.py` | `CaseInvestigation`, `CaseActivity`, `ActivityQuerySet`; separate review fields on `DiscrepancyFinding` |
| `auditcounter_django/discrepancies/migrations/0002_discrepancyfinding_review_basis_and_more.py` | New tables, review fields, one-to-one ownership and closure constraints |
| `auditcounter_django/discrepancies/services.py` → `services/__init__.py` | Existing persistence helpers preserved in a package; `synchronize_findings` invokes renewed-review detection after final synchronization |
| `auditcounter_django/discrepancies/services/investigation.py` | `start_investigation`, `update_investigation`, `add_investigation_note`, `review_finding`, `resolve_investigation`, `reopen_investigation`; revision, locking, current-state/evidence validation, activity and renewed-review helpers |
| `auditcounter_django/discrepancies/presentation.py` | Finding review/staleness serialization and `serialize_investigation` with history, revision and permitted controls |
| `auditcounter_django/accounts_receivable/services/pages.py` | `workspace_state` adds investigation object/revision |
| `auditcounter_django/accounts_receivable/services/http.py` | `perform` routes six case-level investigation actions for AP/AR |
| `auditcounter_django/accounts_receivable/static/accounting/workspace.js` | `caseDetail`, `discrepancyFindings`, `investigationActor`, `investigationOverview`, `findingReview`, `investigationHistory`, `bindInvestigation`; corrected allocation caption |
| `auditcounter_django/discrepancies/investigation_test_support.py` | Shared AP/AR workflow scenarios |
| `auditcounter_django/discrepancies/test_investigation.py` | Ownership, uniqueness and closure database tests |
| `auditcounter_django/discrepancies/test_investigation_concurrency.py` | Real PostgreSQL concurrent start/stale-update test |
| `auditcounter_django/accounts_payable/tests.py` | `PayablesInvestigationTests` |
| `auditcounter_django/accounts_receivable/tests.py` | `ReceivablesInvestigationTests` |
| `auditcounter_django/accounts_receivable/frontend_tests/investigation.test.cjs` | Overview, review/history rendering, escaping, separation of financial components and form payload tests |
| `docs/case-investigation-review-resolution.md` | Implementation/deployment handoff |

Earlier matching, Auto Match and persistent-finding work remains in the working tree.

## Verification

| Executed check | Result |
| --- | --- |
| Full Django suite, from Django project directory | 452 run: 448 passed, 4 PostgreSQL-only skips |
| Findings/AP/AR suite on PostgreSQL 17 | 245 passed, no skips |
| New targeted investigation scenarios/integrity tests | 31 passed |
| Existing/new frontend Node suite | 56 passed |
| `manage.py check` | No issues |
| `makemigrations --check --dry-run` | No changes detected |
| JavaScript syntax and `git diff --check` | Passed |

PostgreSQL tests verify concurrent start creates one investigation/opening event and conflicting updates produce one success and one stale conflict. Existing matching, findings, payment, extraction, database import, routing and migration compatibility tests passed.

Browser QA used disposable SQLite fixtures at `http://127.0.0.1:8765`, desktop 1440×1000 and mobile 390×844. Browser plugin was unavailable, so connected Playwright tools were used. Verified page identity/content, no error overlay, console health, screenshots and actual controls. AP checks covered start, routing, review, note, business-exception closure with reconciliation still `exception` and the finding still open, changed-evidence flagging and reopening with old resolution retained. AR checks covered investigating/waiting transitions, an actual corrective receipt plus split allocations, and document-backed closure after a matched recalculation. Reopening/history/source preservation and mobile page width were inspected. No console errors were observed.

## Deliberate limits

No authentication, verified staff identity, permissions, organization isolation, approvals, messages, notifications, AI, claims/credit-note settlement, refunds/payments, external ERP writes, background jobs or new dependencies were introduced. Correction verification checks the local accounting evidence; it does not certify external document authenticity or funds recovery. Direct SQL/bulk source updates outside supported save hooks require explicit recalculation, as before. History is not a cryptographically signed or database-admin-proof audit ledger. Large-history pagination and team workflows remain deferred.

Work remains in the existing `codex/matching-improvments` checkout. No push, merge or pull request was performed. The original workspace database and external ERP records were not modified during verification.

The disposable Django and PostgreSQL verification services were stopped after QA. Browser/log artifacts were kept outside the repository; pre-existing output folders were preserved.
