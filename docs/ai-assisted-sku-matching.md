# AI-assisted SKU matching and normalization

Implemented for the existing AP and AR reconciliation matching pages. SKU equivalence establishes product identity only. It does not approve prices, quantities, suppliers/customers, currencies, document relationships, discounts, taxes or settlements. Source accounting and ERP values remain unchanged. No authentication, dependencies, background workers or frontend frameworks were added.

## Behavior and normalization

Resolution checks normalized equality first, then approved mappings scoped to AP/AR, supplier/customer, source namespace and normalized unit. Unknown, pending, rejected, deactivated, conflicting or stale canonical targets do not establish equivalence. Exact matching and approved mappings never invoke an LLM.

`normalize_sku` and `normalize_description` apply Unicode NFC, collapse whitespace (including trimming) and casefold. Leading zeros, punctuation, model identifiers, capacity, voltage and variants are preserved. `normalize_unit` additionally recognizes only explicitly listed formatting aliases: pc/pcs/pc./pcs./piece/pieces, ea/ea./each, kg/kgs/kilogram/kilograms, box/boxes. These groups are distinct; there are no unit conversions. Uniformly blank codes in previously saved manual matches retain the earlier compatibility rule; Auto Match still requires explicit product codes and units.

Namespaces are `erp:<database source id>`, `document` for uploaded-document records, and `local` for records without either provenance. All namespaces are additionally supplier/customer scoped. Mappings are directional to a known canonical root; chains and cycles require manual review and are rejected. Two approved aliases may resolve to the same known root. Explicit conflicting capacity, voltage, manufacturer or model evidence prevents equivalence, including when an alias exists.

Approvals require existing same-account source and canonical line references and a written explanation. Canonical products are observations from existing PO, DR or invoice lines, not newly created master products. Pending proposals are reused only when both original source and canonical observations remain unchanged; changed observations produce a fresh proposal while preserving the earlier one. A live canonical code, description, unit, provenance or source-namespace change invalidates the approval's identity proof until reviewed. Source-change hooks refresh dependent cases even when the canonical record is outside their document membership. Deactivation refreshes that account's cases and preserves saved allocations, their original identity proof, mapping history, findings and investigation history.

## Schema and migrations

Apply the new migrations with the existing environment before starting the application:

```bash
python auditcounter_django/manage.py migrate
```

- `sku_matching/migrations/0001_initial.py`: `SKUAlias` and `SKUSuggestionAttempt`. Constraints enforce the AP/supplier or AR/customer relationship, one approved mapping per account/namespace/source code/unit, and an approval timestamp for approved aliases. Party deletion is protected. Rejected and deactivated mappings remain accessible.
- `accounts_payable/migrations/0013_documentmatch_sku_identity_snapshot.py` and `accounts_receivable/migrations/0012_documentmatch_sku_identity_snapshot.py`: add an initially empty JSON identity snapshot to existing `DocumentMatch` rows. New saves record the exact approved mapping and known canonical source snapshot used, including document/database/table IDs and the original external record key. Existing rows and source financial values are preserved; no data backfill fabricates historical approval evidence.

Mapping history appends proposal, approval, rejection and deactivation events with original product snapshots and review explanations. Suggestion attempts retain bounded product inputs, supplied candidate identities, provider/model, request/response metadata, errors, usage and elapsed time. They do not contain whole accounting documents or ERP datasets. There is no mapping deletion endpoint and no verified approver identity.

## Optional AI provider

The SKU service reuses the existing provider-native JSON builder/parser and `document_extraction.services.llm.invoke_with_llm` transport. It does not create an extraction configuration or an extraction log to invoke a provider.

Use the existing `ACCOUNTS_PAYABLE_*` or `ACCOUNTS_RECEIVABLE_*` environment settings: `LLM_PROVIDER`, `<PROVIDER>_MODEL`, existing provider credentials/base URL, `MAX_OUTPUT_TOKENS`, and `LLM_TIMEOUT_SECONDS`. Supported adapters remain OpenAI, Anthropic, Google, Ollama, Alibaba and DeepSeek. No extra credential store was added.

Candidate selection inspects at most 2,000 known same-account product lines, supplies at most ten distinct plausible candidates, and excludes normalized duplicates and incompatible units/specifications. A candidate must share an observed SKU token, meaningful description token, manufacturer, model, capacity or voltage. Explicit measurement comparisons use Decimal. Candidate ordering is deterministic, but ordering is never approval.

The request contains product fields only, descriptions truncated to 2,000 characters, a maximum 40,000-character serialized product context, and at most 2,048 output tokens. The schema requires the original source code, a supplied candidate ID and exact target code (or a null proposal), supported shared-attribute names, a reason, and `requires_review: true`. Descriptions are explicitly treated as untrusted data. Local validation rejects malformed JSON, unknown fields, invented targets, unsupported attributes, incompatible specifications and attempts to waive review. Free-text model reasoning remains an unverified proposal for the human reviewer.

Provider I/O runs without row locks. Before creating a pending alias, source and candidate observations are checked again under an account lock. Source/mapping changes during the request discard the proposal. Failures, refusals and no-candidate outcomes are logged; deterministic matching and manual approval remain available. No provider response can approve an alias.

## API and review workflow

Existing CSRF-protected POST routing is reused at `/accounts-payable/api/<action>/<case_id>/` and `/accounts-receivable/api/<action>/<case_id>/`:

| Action | Request beyond the catalog revision | Result |
|---|---|---|
| `sku-mappings` | None (revision optional for this read-only action) | Current scoped products, mappings, histories and recent attempts |
| `sku-suggest` | `source_reference` | An attempt, optionally a pending proposal; never an allocation or approval |
| `sku-approve` | Known `source_reference`, `canonical_reference`, `approval_notes`; or `alias_id`, `alias_revision`, `approval_notes` | Explicit approval and account-case recalculation |
| `sku-reject` | `alias_id`, `alias_revision`, `reason` | Rejected pending proposal, preserving history |
| `sku-deactivate` | `alias_id`, `alias_revision`, `reason` | Disabled approved mapping and account-case recalculation |

A product reference is `{kind: "sales_invoice" | "purchase_order" | "delivery_receipt", record_id: <integer>, line_id: <integer>}`. Mutating actions require the current `revision` returned in `sku.revision`; alias reviews additionally require the alias revision. Unknown fields and unrelated account references are rejected. Stale writes return 409; invalid requests return 400. Locks serialize account-level approvals, and conditional unique constraints provide a final conflict guard. Invalid operations roll back without leaving a partial proposal/approval.

The matching page's **SKU matching assistance** section displays original codes/descriptions, namespace/unit, original accounting/document/database links, known canonical selections, proposals, review explanations, statuses, mapping history and recent AI errors. Users can request AI suggestions, manually select a known equivalent, approve/reject pending proposals and deactivate approvals. AI suggestion generation does not modify allocation drafts. Identity-changing review actions preserve draft rows, clear stale Auto Match proposals and require another authoritative backend preview before saving. Approved mappings are then available to both manual matching and Auto Match, including split deliveries.

## Exact implementation inventory

All paths below are relative to the repository root.

| File | Models/functions changed or added |
|---|---|
| `auditcounter_django/sku_matching/apps.py`, `__init__.py`, `services/__init__.py` | Shared app setup and source-change hook registration |
| `auditcounter_django/sku_matching/models.py` | `SKUAlias`, `SKUSuggestionAttempt`, scoped uniqueness/check constraints |
| `auditcounter_django/sku_matching/services/normalization.py` | `normalize_sku`, `normalize_description`, `normalize_unit`, `specifications`, `incompatible_specs` |
| `auditcounter_django/sku_matching/services/products.py` | `mode_for`, `parent_for`, `namespace`, `reference`, `product`, `party_filter`, `get_line`, `known_lines`, `case_lines` |
| `auditcounter_django/sku_matching/services/mapping.py` | `resolver_session`, `find_approved_mapping`, `resolve_product_identity`, `compare_products`, `identity_for_match`, catalog/alias snapshots and revisions, `pending_alias`, `approve_mapping`, `reject_mapping`, `deactivate_mapping`, atomic locking and refresh helpers |
| `auditcounter_django/sku_matching/services/suggestions.py` | `find_product_candidates`, `shared_attributes`, `validate_suggestion`, `prompt_product`, `suggest_sku_equivalence`, bounded structured request schema |
| `auditcounter_django/sku_matching/services/presentation.py` | `record_url`, `present_product`, `workspace_state` |
| `auditcounter_django/sku_matching/signals.py` | `canonical_changed`, source-header/line save/delete handlers for dependent cases |
| `auditcounter_django/sku_matching/tests.py`, `test_concurrency.py` | Normalization, AP/AR mapping, financial safety, AI failure/validation, API, history, canonical-source changes and real PostgreSQL concurrent-approval tests |
| `auditcounter_django/sku_matching/migrations/__init__.py`, `0001_initial.py` | SKU schema migration |
| `auditcounter_django/accounts_payable/models.py`, `accounts_receivable/models.py` | `DocumentMatch.sku_identity_snapshot`; `DocumentMatch.save` account/case locks and captured identity proof |
| `auditcounter_django/accounts_payable/migrations/0013_documentmatch_sku_identity_snapshot.py`, `accounts_receivable/migrations/0012_documentmatch_sku_identity_snapshot.py` | Existing match identity snapshot fields |
| `auditcounter_django/accounts_payable/services/reconciliation.py`, `accounts_receivable/services/reconciliation.py` | `validate_match` approved identity resolver and explicit unit normalization; other financial safeguards retained |
| `auditcounter_django/accounts_receivable/services/evaluation.py` | `evaluate_reconciliation` operation-local resolver cache, evaluated matches use current case context |
| `auditcounter_django/accounts_receivable/services/auto_matching.py` | `normalize_item_code`, `source_revision`, `find_candidate_lines`, `evaluate_match_candidate`, `generate_match_suggestions` approved-mapping integration |
| `auditcounter_django/accounts_receivable/services/llm.py` | Extract reusable `build_json_payload` / `parse_json_response`; existing `run` retains provider transport/logging behavior |
| `auditcounter_django/accounts_receivable/services/http.py` | `perform` SKU actions and updated matching revision after identity-changing review |
| `auditcounter_django/accounts_receivable/services/pages.py`, `accounts_receivable/ui.py` | Matching-page-only SKU serialization in `workspace_state` / `render_workspace`; saved proof in comparison rows |
| `auditcounter_django/accounts_receivable/static/accounting/workspace.js` | `skuAssistance`, `bindSkuAssistance`, `matching`: review controls, source links, errors and draft preservation |
| `auditcounter_django/accounts_receivable/frontend_tests/sku-matching.test.cjs` | Seven SKU UI tests, including explicit approval and stale/failure behavior |
| `auditcounter_django/discrepancies/evaluation.py` | `source_evidence`, `compatible_evidence`, `allocation_evidence`: original descriptions and mapping evidence |
| `auditcounter_django/discrepancies/services/investigation.py` | `evidence_state` includes applicable approvals so changed identity evidence flags closed investigations for review |
| `auditcounter_django/auditcounter_django/settings.py` | Register `sku_matching` |
| `docs/ai-assisted-sku-matching.md` | Implementation, deployment, API and verification notes |

This inventory covers this SKU milestone. Earlier matching/findings/investigation work already present in the working tree is retained.

## Executed verification

- Full Django discovery from `auditcounter_django`: `../.venv/bin/python manage.py test --noinput` — **495 run, 490 passed, 5 skipped** (PostgreSQL-only locking tests).
- PostgreSQL: `DB_ENGINE=django.db.backends.postgresql DB_NAME=postgres DB_USER=aladinyu DB_HOST=127.0.0.1 DB_PORT=55432 .venv/bin/python auditcounter_django/manage.py test sku_matching accounts_payable accounts_receivable discrepancies --noinput` — **288 passed, zero skipped**. Includes conflicting SKU approval contention and existing AP/AR allocation/investigation lock tests.
- Frontend: `node --test auditcounter_django/accounts_receivable/frontend_tests/*.test.cjs auditcounter_django/router/frontend_tests/*.test.cjs` — **70 passed**.
- `python auditcounter_django/manage.py makemigrations --check --dry-run` — no changes detected.
- `python auditcounter_django/manage.py check` — no issues.
- New migrations applied successfully to a disposable SQLite QA database; PostgreSQL test-database migration creation also succeeded.
- `git diff --check` and JavaScript syntax check passed.

### Browser QA

Browser plugin not available; connected Playwright was used. Environment: loopback-only `http://127.0.0.1:8765`, disposable SQLite database, desktop 1440×1050 and mobile 390×844. Provider requests used an explicitly local Ollama-compatible test stub, then a simulated HTTP 503 failure. No live external LLM output quality was tested.

| Check | Result |
|---|---|
| Page URL/title and meaningful content | Pass: AP/AR reconciliation matching pages |
| Framework error overlay | None |
| Console health | Zero warnings/errors |
| Desktop/mobile screenshots | Captured and inspected; no horizontal mobile overflow (390px document and viewport) |
| Interaction loop | Pass: request → pending → approve/reject; manual approval after provider failure; Auto Match → accept split deliveries → backend preview → save → reopen |
| Existing draft preservation | Pass: the manually entered 60-unit allocation survived AI request and approval; Auto Match supplied the remaining 40 units |
| Backend consistency | Pass: partial 60-unit preview became matched/zero discrepancy after 100 units were supported |
| Deactivation | Pass: original two saved allocations remained; backend case returned to exception and mapping history remained |

Screenshot evidence is outside the repository: `/private/tmp/sku-approved-desktop.png` and `/private/tmp/sku-approved-mobile.png`. Temporary QA services are stopped after verification. Browser QA did not use the user's live database.

## Compatibility and intentional limits

Public reconciliation tuple contracts and manual/Auto Match persistence remain unchanged. Empty new snapshot fields preserve old rows; earlier identity evidence is not fabricated. Existing extraction/provider, payment, routing, findings and investigation tests pass. New identity validation intentionally requires review for explicit product/specification conflicts and deactivated or stale canonical mappings. Source-change hooks cover normal saves/deletes; direct SQL and `QuerySet.update` continue to require the existing explicit reconciliation refresh pathways.

AI is optional, synchronous and never authoritative. Candidate search is bounded, scoped and deliberately conservative; this is not a complete product catalog search. Unsupported units, uncertain models/specifications, missing product evidence and alias chains require human investigation. There is no fuzzy automatic equivalence, embedding database, inventory master, autonomous approval, ERP write-back or product creation. Live provider credentials, model quality and other browsers were not verified. Mapping history is preserved through the service API, without a new database-level immutable-history subsystem.
