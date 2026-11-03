# Discrepancies, investigations and evidence

Shared AP/AR infrastructure for persistent findings, source snapshots, human
investigation, supplier claims, chronological evidence and reviewed outcome analytics.
It extends existing accounting `Transaction` cases rather than replacing them.

## Application flow

```mermaid
flowchart TD
    A[Explicit accounting write / case recalculation] --> B[Pure document and settlement evaluation]
    B --> C[Synchronize stable case-scoped findings atomically]
    C --> D[Capture deduplicated original evidence snapshots]
    C --> E[Clear corrected findings without deleting history]
    D --> F[Human starts existing case investigation]
    F --> G[Review evidence and record independent finding decisions]
    G --> H[Notes / department / next action / workflow transitions]
    H --> I[Document resolution or reopen with explanation]
    G --> J[Optional reviewed root cause]
    G --> K[AP supplier claim and manually logged correspondence]
    K --> L[Verify credit application or replacement evidence before claim closure]
    A --> M[Append meaningful automatic timeline transitions]
    H --> N[Append human CaseActivity]
    M --> O[Read-only unified timeline and dashboard]
    N --> O
    J --> P[Read-only filtered analytics by module and currency]
    L --> P
```

## Setup and operation

```bash
python auditcounter_django/manage.py migrate
python auditcounter_django/manage.py runserver 127.0.0.1:8000
```

Open `/discrepancies/` to search existing AP and AR cases. Open a case's original
accounting detail page to inspect findings, source documents, settlement, investigation
and timeline. Dashboard and timeline GETs do not recalculate or persist accounting
state. No login is required; retain the existing CSRF protection for writes.

1. Save matching/source changes or use explicit recalculation to evaluate current data.
2. Start an investigation; confirm, dismiss or request more evidence for individual
   findings. A manual staff label is optional and explicitly unverified.
3. Record notes, responsible department, next action and allowed workflow transitions.
4. Resolve with a documented type, explanation and supporting references when required.
   Reopen closed work with a reason; earlier resolutions and activities remain.
5. For AP, create a claim from current confirmed findings, prepare a copyable draft,
   manually log communications, and verify actual applied credit or replacement evidence.
6. Attribute root causes only after reviewing current evidence. Changed evidence flags
   earlier attributions or contradicted claim resolutions for renewed review.

## State and financial rules

| State | Meaning / authority |
|---|---|
| Reconciliation `pending`, `partial`, `matched`, `exception` | Computed accounting evidence result on the existing AP/AR case |
| Finding `open`, `cleared` | Whether a deterministic discrepancy remains detected |
| Finding review | `unreviewed`, `confirmed`, `dismissed`, `needs_more_evidence`; human decision |
| Investigation | `needs_review`, `investigating`, `waiting`, `resolved`, `dismissed`; human workflow |
| Root cause | Human-confirmed attribution or `needs_review` after supporting basis changes |

Do not assign one state from another. Investigation/claim closure does not mark a
physical discrepancy matched, clear a finding, or establish cash recovery. Findings
can describe overlapping arithmetic errors; financial summaries use persisted case
differences, not sums of finding amounts. Currencies and AP/AR are separate namespaces.

Finding identity uses a stable fingerprint, not a changing amount. Repeated unchanged
refreshes do not duplicate findings, evidence or automatic events. Legitimate recurring
transitions remain historical. `CaseActivity` and automatic events are append-only.
Timeline aggregation reuses human activities and available historical timestamps;
it does not invent pre-tracking observations. Duplicate invoice candidates can exist
without a case and never automatically delete or reject source invoices.

## Services and APIs

| Module / route | Purpose |
|---|---|
| `services/__init__.py`, `evaluation.py` | Pure finding results, atomic synchronization, evidence snapshots and deferred batch refresh |
| `services/investigation.py` | Locked, revision-checked reviews, notes, resolution and reopening |
| `services/timeline.py` | Idempotent automatic transitions and read-only historical aggregation |
| `services/dashboard.py`, `presentation.py` | Bounded shared case queries, filters and serialization |
| `services/duplicate_invoices.py` | Bounded candidate detection and historical human review |
| `services/claims.py`, `services/analytics.py` | Supplier claim workflows and reviewed cause/outcome aggregates |
| `GET /discrepancies/api/cases/`, `api/summary/` | Unified case list and filter-aware summary |
| `GET /discrepancies/api/cases/<ap-or-ar>/<id>/timeline/` | Category-filtered chronological timeline, bounded pagination |
| `GET /discrepancies/api/duplicate-invoices/` | Suspected invoice pairs with review history |
| `POST /discrepancies/api/duplicate-invoices/<id>/review/` | Explicit candidate review with revision and explanation |
| `GET /discrepancies/api/analytics/` | Module, party, dates, currency, finding, root-cause and investigation filters |

Investigation, finding-review, claim and `root-cause-review/<case_id>` writes use the
existing `/accounts-payable/api/` or `/accounts-receivable/api/` actions in shared
`accounts_receivable/services/http.py`. Read APIs validate filters and use bounded page
sizes. Writes reuse account/case locks, atomic operations, revisions and evidence scope.
Source record identifiers inside `FindingEvidence` are generic references; its explicit
document/database FKs and preserved JSON identify the source without fabricated OCR coordinates.

## Tests and limits

```bash
python auditcounter_django/manage.py test discrepancies accounts_payable accounts_receivable --noinput
node --test auditcounter_django/accounts_receivable/frontend_tests/*.test.cjs
```

PostgreSQL is required for independent-connection locking tests. Existing historical
data remains readable, but observations predating tracking may be incomplete. Supplier
correspondence is manually recorded; no email is sent. Cash refunds/recovery tracking,
exchange-rate conversion, assignment/approval hierarchies and background workers are
outside the MVP. See [implementation notes](../../docs/mvp-implementation-report.md)
and the [exact feature inventory](../../docs/mvp-file-inventory.md).

## Model ERD

These logical diagrams reflect the current Django model definitions. Key fields are
shown; external entities appear as primary-key stubs and include their app prefix.
`||` means exactly one, `|o` / `o|` zero or one, and `o{` / `}o` zero or more.
FK optionality is represented on the parent side; one-to-one/unique FKs limit children.
Many-to-many lines represent Django-managed join tables; service validation may impose
stronger business constraints than these structural cardinalities.

### Findings and investigation history

```mermaid
erDiagram
    discrepancies_DiscrepancyFinding {
        int id PK
        int ap_transaction FK
        int ar_transaction FK
        string fingerprint
        string finding_code
        string severity
        string status
        decimal difference_amount
        string review_decision
    }
    discrepancies_FindingEvidence {
        int id PK
        int finding FK
        int source_document FK
        int source_database FK
        json source_record_key
    }
    discrepancies_CaseInvestigation {
        int id PK
        int ap_transaction FK
        int ar_transaction FK
        string workflow_status
        string resolution_type
    }
    discrepancies_CaseActivity {
        int id PK
        int investigation FK
        int finding FK
        string activity_type
    }
    discrepancies_CaseTimelineEvent {
        int id PK
        int ap_transaction FK
        int ar_transaction FK
        string event_type
        string event_key
    }
    discrepancies_FindingRootCause {
        int id PK
        int finding FK
        string category
        string review_status
    }
    accounts_payable_Transaction {
        int transaction_no PK
    }
    accounts_receivable_Transaction {
        int transaction_no PK
    }
    db_extraction_DatabaseSource {
        int id PK
    }
    document_extraction_Document {
        int document_no PK
    }
    accounts_payable_Transaction |o--o{ discrepancies_DiscrepancyFinding : "ap_transaction"
    accounts_receivable_Transaction |o--o{ discrepancies_DiscrepancyFinding : "ar_transaction"
    discrepancies_DiscrepancyFinding ||--o{ discrepancies_FindingEvidence : "finding"
    document_extraction_Document |o--o{ discrepancies_FindingEvidence : "source_document"
    db_extraction_DatabaseSource |o--o{ discrepancies_FindingEvidence : "source_database"
    accounts_payable_Transaction |o--o| discrepancies_CaseInvestigation : "ap_transaction"
    accounts_receivable_Transaction |o--o| discrepancies_CaseInvestigation : "ar_transaction"
    discrepancies_CaseInvestigation ||--o{ discrepancies_CaseActivity : "investigation"
    discrepancies_DiscrepancyFinding |o--o{ discrepancies_CaseActivity : "finding"
    accounts_payable_Transaction |o--o{ discrepancies_CaseTimelineEvent : "ap_transaction"
    accounts_receivable_Transaction |o--o{ discrepancies_CaseTimelineEvent : "ar_transaction"
    discrepancies_DiscrepancyFinding ||--o| discrepancies_FindingRootCause : "finding"
    discrepancies_FindingRootCause }o--o{ discrepancies_FindingEvidence : "evidence"
```

### Duplicate review and supplier claims

```mermaid
erDiagram
    discrepancies_DuplicateInvoiceCandidate {
        int id PK
        int ap_first FK
        int ap_second FK
        int ar_first FK
        int ar_second FK
        string review_decision
        string review_basis
    }
    discrepancies_DuplicateInvoiceReview {
        int id PK
        int candidate FK
        string decision
        string notes
        json evidence_snapshot
    }
    discrepancies_SupplierClaim {
        int id PK
        int ap_transaction FK
        int supplier FK
        int settlement_application FK
        int replacement_document FK
        string reference
        decimal claimed_amount
        decimal accepted_amount
        string status
    }
    discrepancies_ClaimCorrespondence {
        int id PK
        int claim FK
        int source_document FK
        string direction
    }
    accounts_payable_Supplier {
        int supplier_no PK
    }
    accounts_payable_SupplierCreditApplication {
        int id PK
    }
    accounts_payable_SupplierSalesInvoice {
        int supplier_sales_invoice_no PK
    }
    accounts_payable_Transaction {
        int transaction_no PK
    }
    accounts_receivable_CompanySalesInvoice {
        int company_sales_invoice_no PK
    }
    discrepancies_DiscrepancyFinding {
        int id PK
    }
    discrepancies_FindingEvidence {
        int id PK
    }
    document_extraction_Document {
        int document_no PK
    }
    accounts_payable_SupplierSalesInvoice |o--o{ discrepancies_DuplicateInvoiceCandidate : "ap_first"
    accounts_payable_SupplierSalesInvoice |o--o{ discrepancies_DuplicateInvoiceCandidate : "ap_second"
    accounts_receivable_CompanySalesInvoice |o--o{ discrepancies_DuplicateInvoiceCandidate : "ar_first"
    accounts_receivable_CompanySalesInvoice |o--o{ discrepancies_DuplicateInvoiceCandidate : "ar_second"
    discrepancies_DuplicateInvoiceCandidate ||--o{ discrepancies_DuplicateInvoiceReview : "candidate"
    accounts_payable_Transaction ||--o{ discrepancies_SupplierClaim : "ap_transaction"
    accounts_payable_Supplier ||--o{ discrepancies_SupplierClaim : "supplier"
    accounts_payable_SupplierCreditApplication |o--o| discrepancies_SupplierClaim : "settlement_application"
    document_extraction_Document |o--o{ discrepancies_SupplierClaim : "replacement_document"
    discrepancies_SupplierClaim }o--o{ discrepancies_DiscrepancyFinding : "findings"
    discrepancies_SupplierClaim }o--o{ discrepancies_FindingEvidence : "evidence"
    discrepancies_SupplierClaim ||--o{ discrepancies_ClaimCorrespondence : "claim"
    document_extraction_Document |o--o{ discrepancies_ClaimCorrespondence : "source_document"
```

### Model responsibilities

| Model | Responsibility |
|---|---|
| `DiscrepancyFinding` | Stable case-scoped deterministic finding and independent human review. |
| `FindingEvidence` | Deduplicated immutable source observations and finding snapshots. |
| `CaseInvestigation` | Human workflow for exactly one existing AP or AR case. |
| `CaseActivity` | Append-only investigation notes, transitions, reviews and resolutions. |
| `CaseTimelineEvent` | Append-only automatic business transitions; existing human activity is aggregated separately. |
| `DuplicateInvoiceCandidate` | Ordered AP or AR invoice pair, including candidates outside a reconciliation case. |
| `DuplicateInvoiceReview` | Historical detection/clearance and human review snapshots. |
| `SupplierClaim` | AP claim backed by reviewed findings/evidence and protected settlement references. |
| `ClaimCorrespondence` | Manually logged supplier correspondence; messages are not sent automatically. |
| `FindingRootCause` | Current reviewed cause with selected evidence; prior decisions remain CaseActivity. |

For every field, delete policy, conditional constraint and index, consult
[`models.py`](models.py) and the additive [`migrations/`](migrations/). These diagrams
do not imply that an unmigrated database already has the same schema.
