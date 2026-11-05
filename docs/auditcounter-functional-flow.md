# How AuditCounter works: detailed functional flow

This guide describes the **current workspace code**, including uncommitted features. It is a map of implemented flows, not proof that a particular running instance has the latest migrations, settings, provider credentials, or data. Diagrams are split to keep them readable and avoid Mermaid's maximum text-size limit.

## 1. The whole system

```mermaid
flowchart TD
    Start([User opens AuditCounter]) --> Setup[Configure selected modules, providers, rules and sources]
    Setup --> Input{How does information enter?}
    Input -->|Files| Documents[Documents and batches]
    Input -->|PostgreSQL| Database[Database connections and schema discovery]
    Documents --> Extract[Extract and review text]
    Extract --> Route[Route document to one or more destinations]
    Route -->|AP or AR| DocAccounting[Extract structured accounting record]
    Route -->|Encoder| Encoder[Prepare and review MCP tool payload]
    Database --> Mapping[Build query and map source fields]
    Mapping --> Review[Preview, full validation and user confirmation]
    Review --> Local[(AuditCounter application database)]
    DocAccounting --> Local
    Local --> AP[Accounts payable: supplier-facing records]
    Local --> AR[Accounts receivable: customer-facing records]
    AP --> Cases[Create and maintain reconciliation cases]
    AR --> Cases
    Cases --> Match[Match orders, receipts and invoices]
    Match --> Findings[Calculate discrepancies and preserve evidence]
    AP --> Settlement[Evaluate payment and adjustment settlement]
    AR --> Settlement
    Settlement --> Findings
    Findings --> Investigate[Review findings, investigate and record decisions]
    Investigate --> Actions[Claims, credits, statements, deductions and root causes]
    Actions --> Reports[Dashboards, aging and analytics]
    Encoder -->|Explicit confirmation| External[Permitted external MCP operation]
    Local --> History[Source links, extraction logs, configuration snapshots and timeline]
    Route --> History
    Investigate --> History
```

AuditCounter maintains its **own application database**, distinct from any PostgreSQL source or external system. Documents and external database records are alternative ways to populate accounting records; either can be used without the other. AP and AR have separate models and rules, but share parts of the interface and service layer. The Router can send a document to more than one independent destination. The optional Encoder is a separate external-write path, not a prerequisite for reconciliation.

## 2. Document intake, extraction and routing

```mermaid
flowchart TD
    Upload[Upload file or organize documents in a batch] --> Store[Store original document and metadata]
    Store --> Type{Input type and extraction method}
    Type -->|Supported text-based file| Parse[Extract text from PDF, DOCX, Excel, TXT or CSV]
    Type -->|Image or provider-dependent extraction| Provider[Call configured provider and suitable model]
    Type -->|Scanned PDF| OCR[Requires an OCR workflow]
    Parse --> Save[Save extraction result and activity]
    Provider --> Save
    OCR --> Save
    Save --> Review[User inspects and may edit/review extracted text]
    Review --> RouteRequest[Route document, selection or batch]
    RouteRequest --> Select[Select latest usable text; prefer latest marked accurate]
    Select --> Confirm{Source review requires confirmation?}
    Confirm -->|Yes| Second[Explicit second confirmation; recheck source revisions]
    Confirm -->|No| Rules[Evaluate active routing rules with configured LLM]
    Second --> Rules
    Rules --> Decisions{Validated destinations}
    Decisions -->|None| NoMatch[Record routing attempt; no destination]
    Decisions -->|One or more| Routes[Create separate route decisions and activity]
    Routes --> APAR{Destination type}
    APAR -->|AP or AR| Config{Matching submitted document configuration?}
    Config -->|One applicable setup| Auto[Start accounting extraction automatically]
    Config -->|Several choices| Choose[Choose configuration and process record]
    Config -->|Missing or invalid| Fix[Correct setup or source, then retry]
    Auto --> Validate[Validate account, fields, lines and totals]
    Choose --> Validate
    Validate -->|Valid| Record[Save header and optional lines atomically]
    Validate -->|Invalid| Fail[Save attempt and errors; no partial accounting record]
    APAR -->|Encoder| Prepare[Create Encoder job and prepare payload]
    Record --> Human[Route review remains a separate human decision]
    Fail --> Fix
```

Routing **does not imply human approval**. An LLM-matched AP/AR route can start extraction while the route is still pending review. Completed routes are protected from repeat processing. Source text, attempt logs, errors and configuration snapshots provide traceability. Manually added destinations process on approval. Text-based parsing and provider extraction have different capabilities; a scanned PDF needs an appropriate OCR workflow. File size and parser limits are documented in the [project README](../README.md).

An AP/AR document configuration defines the target record, instructions, field rules and account lookup. A test is a preview; activation requires review and confirmation. The configuration assistant can suggest settings, but proposals must be applied and the configuration submitted separately. A document route normally produces one accounting header and its optional lines; split documents that contain multiple target invoices.

## 3. PostgreSQL setup, migration and later updates

```mermaid
flowchart TD
    Connect[Create and test external PostgreSQL connection] --> Schema[Refresh and save schema snapshot]
    Schema --> Select[Choose AP or AR, target record and source table]
    Select --> Shape[Prepare rows: joins, JSON expansion, filters, conversions and sorting]
    Shape --> Map[Map source columns to target fields and account lookup]
    Map --> Preview[Test query with sample rows]
    Preview --> Quality{Mapping and schema usable?}
    Quality -->|No| Repair[Correct source, mappings or conversions; retest]
    Repair --> Preview
    Quality -->|Yes| Full[Review every matching source identity]
    Full --> Errors{Any validation errors?}
    Errors -->|Yes| Repair
    Errors -->|No| Confirm[Review create, update and unchanged counts; confirm migration]
    Confirm --> Recheck[Revalidate reviewed data and source state]
    Recheck -->|Changed or invalid| Stop[Reject or roll back; review again]
    Recheck -->|Valid| Commit[Atomically save accounting records and active configuration]
    Commit --> Run[Record import run and configuration snapshot]
    Run --> Later[Later: Review all data updates]
    Later --> Diff[Identify new, changed and unchanged source identities]
    Diff --> Block{Protected or finalized record would change?}
    Block -->|Yes| Resolve[Report conflict for resolution]
    Block -->|No errors and user confirms| Update[Create new records, update permitted mapped fields, skip unchanged]
    Update --> Keep[Keep local records absent from source; record run history]
```

Source queries use read-only transactions; migration writes to AuditCounter's application database, not the external PostgreSQL source. The complete migration is reviewed and then revalidated at confirmation. A failure during the commit rolls back the accounting and configuration changes. Updates preserve unmapped accounting fields and do not delete local records that disappear from the source. Records already used in reconciliation or otherwise protected can block changes. Schema drift checks use the latest **completed snapshot**, so refresh the schema to inspect recent external changes. See [database migration and updates](../auditcounter_django/accounts_receivable/DATABASE_MIGRATION.md) and the [query builder guide](../auditcounter_django/accounts_receivable/QUERY_BUILDER.md).

## 4. AP and AR accounting records

| Concept | Accounts payable | Accounts receivable |
| --- | --- | --- |
| Counterparty | Supplier | Customer |
| Order | Company purchase order | Customer purchase order |
| Delivery | Supplier delivery receipt | Company delivery receipt |
| Invoice | Supplier sales invoice | Company sales invoice |
| Payment | Company payment | Customer payment |
| Other adjustments | Supplier credit notes and applications | Customer deductions and applications |

```mermaid
flowchart LR
    Party[Supplier or customer] --> PO[Purchase order and optional lines]
    Party --> DR[Delivery receipt and optional lines]
    Party --> SI[Sales invoice and optional lines]
    Party --> Pay[Payment]
    PO --> Case[Reconciliation case / transaction]
    DR --> Case
    SI --> Case
    Case --> LM[Line-level document matches]
    PO --> LM
    DR --> LM
    SI --> LM
    Pay --> Allocation[Payment allocation]
    SI --> Allocation
    SI --> Balance[Invoice settlement and outstanding balance]
    Allocation --> Balance
    Credit[Verified applied supplier credit] --> Balance
    Deduction[Accepted and applied customer deduction] --> Balance
```

A case groups related records for a party. It can link multiple orders, delivery receipts and invoices; partial deliveries and shared quantities require explicit capacity checks. Payment allocations are separate from line matching. Accounting amounts use decimal arithmetic. Only cleared payments contribute as cleared settlement; withholding and discounts are displayed separately. Currencies remain separate and there is no currency conversion.

## 5. Matching, findings and investigation

```mermaid
flowchart TD
    Case[Create or open AP or AR case] --> Attach[Attach relevant purchase orders, delivery receipts and invoices]
    Attach --> Check[Validate party, currency, document state and line data]
    Check --> Candidates[Generate or review candidate line matches]
    Candidates --> SKU{Are item identities compatible?}
    SKU -->|Same or approved alias| Capacity[Check available quantities and amounts]
    SKU -->|Unknown or ambiguous| Alias[Review SKU suggestions and approve an alias when justified]
    Alias --> Candidates
    Capacity -->|Valid| SaveMatch[Save match allocation]
    Capacity -->|Invalid or insufficient| Correct[Correct selection, quantity or source data]
    Correct --> Candidates
    SaveMatch --> Evaluate[Evaluate order, receipt and invoice quantities and monetary values]
    Evaluate --> Status[Update case status and recorded difference]
    Status --> Findings[Refresh discrepancy findings and evidence snapshots]
    Findings --> Review[User reviews finding and supporting evidence]
    Review --> Investigation[Record investigation status, notes and timeline]
    Investigation --> Cause{Root cause confirmed by a person?}
    Cause -->|Yes| Attribution[Save category, explanation and supporting evidence]
    Cause -->|Not yet| Followup[Continue investigation]
    Attribution --> Changes{Source or evidence changes?}
    Changes -->|Yes| Renew[Preserve history and flag affected reviews for renewed attention]
    Changes -->|No| Report[Include eligible current results in analytics]
```

A match is not merely a text comparison: the system validates document state, item identity, quantities, amounts and available capacity. SKU normalization and approved aliases help relate different product codes; ambiguous matches need review. Line arithmetic is checked against quantity, unit price, discount and tax where the necessary values exist. Reconciliation uses a configured price tolerance, one cent by default. Findings and their evidence support investigation; they are not automatically proof of fraud or recoverable loss.

## 6. Settlement, credits, deductions and supplier statements

```mermaid
flowchart TD
    Invoice[Saved invoice] --> Settlement[Evaluate invoice settlement separately from document match]
    Payment[Payment and allocation] --> State{Payment cleared?}
    State -->|Yes| Cash[Count eligible cleared cash and separate withholding/discount]
    State -->|Pending or reversed| Pending[Show relevant pending or reversed state; do not treat as cleared cash]
    Cash --> Settlement
    Pending --> Settlement
    AP[AP: manually record supplier credit with evidence] --> Verify[Verify credit]
    Verify --> ApplyCredit[Explicitly apply some or all to eligible invoice]
    ApplyCredit --> Settlement
    ApplyCredit --> ReverseCredit[Explicit reversal restores available balance and preserves history]
    AR[AR: manually record customer deduction with evidence] --> Review[Review: pending, accepted or rejected]
    Review -->|Accepted| ApplyDeduction[Explicitly apply eligible accepted amount]
    ApplyDeduction --> Settlement
    ApplyDeduction --> ReverseDeduction[Explicit reversal restores balance and preserves history]
    Settlement --> Result[Outstanding, partial, settled or needs review]
    Settlement -->|Inconsistent evidence or over-reservation| Finding[Settlement mismatch finding]
    Statement[AP: upload source and enter structured statement CSV] --> Compare[Compare statement lines with eligible invoice, payment and verified credit records]
    Compare --> Ambiguous{Ambiguous or missing match?}
    Ambiguous -->|Yes| Manual[Review and choose supported ledger match or investigate]
    Ambiguous -->|No| Eval[Save statement evaluation and evidence]
    Manual --> Eval
    Eval -->|Linked case and mismatch| StatementFinding[Refresh nonmonetary statement finding]
```

Matching and settlement answer different questions: matching compares business documents; settlement explains how an invoice balance is covered. A credit is not cash, and accepting a deduction alone does not adjust the invoice: an explicit application is required. Statement reconciliation compares recorded statement lines with the ledger; it does not apply credits or create payments. Current statement entry uses structured CSV plus an uploaded original, up to 500 rows; direct PDF/Excel statement parsing is not exposed.

## 7. Duplicate invoices, supplier claims and analytics

```mermaid
flowchart TD
    Invoice[Invoice saved or user requests duplicate scan] --> Detect[Compare same party, currency and amount; near dates and normalized reference]
    Detect --> Candidate{Possible duplicate?}
    Candidate -->|Yes| Pair[Save reviewable candidate pair and evidence]
    Candidate -->|No| End1[No duplicate candidate from this rule]
    Pair --> Decision[Human reviews pair; preserve decisions and source history]
    Decision -->|Case linked| DupFinding[Possible duplicate finding; no automatic deletion]
    Confirmed[AP finding confirmed with supporting evidence] --> Claim[Create supplier claim within available case capacity]
    Claim --> Draft[Prepare copyable draft and record correspondence manually]
    Draft --> ClaimStatus[Track submitted, waiting, accepted or rejected]
    ClaimStatus --> Resolution{Supported resolution?}
    Resolution -->|Accepted and verified credit application| Close[Record closure and supporting evidence]
    Resolution -->|Cleared findings and replacement receiving document| Close
    Resolution -->|Rejected| NoRecovery[Close with documented no-recovery]
    Close --> Reversal{Supporting credit later reversed?}
    Reversal -->|Yes| Renew[Flag claim for renewed review; retain history]
    DupFinding --> Dashboard[Discrepancy dashboard and analytics]
    NoRecovery --> Dashboard
    Close --> Dashboard
    Reviewed[Reviewed findings and human root-cause attribution] --> Dashboard
    Dashboard --> Filters[Filter by module, party, currency, dates, finding, cause or investigation status]
    Filters --> Metrics[Show counts, case differences, claims, applied credits and deductions]
```

Duplicate detection is conservative: it compares normalized references and dates within three days for invoices with the same party, currency and recorded total. It may miss other duplicates and does not automatically delete anything. Claims and correspondence are manual; the application does not send email. Claim closure needs supported evidence. Analytics distinguish historical finding confirmations, current reviewed root causes, case differences and applied adjustments; they do not infer cash recoveries or sum individual findings as independent losses.

## 8. Optional Encoder and external operation

```mermaid
flowchart TD
    Route[Router sends a document to an Encoder destination] --> Job[Create job with connection and permitted operation snapshot]
    Job --> Discover[Inspect tool schema and choose reusable mapping]
    Discover --> Draft[Prepare payload from source extraction]
    Draft --> Missing{Missing or invalid values?}
    Missing -->|Yes| Assist[Request contextual assistance or provide details]
    Assist --> ReviewProposal[Inspect proposal and explicitly apply selected corrections]
    ReviewProposal --> Validate[Validate payload against tool schema]
    Missing -->|No| Validate
    Validate -->|Errors| Draft
    Validate -->|Valid| Approval{Source and route approvals complete?}
    Approval -->|No| Wait[Obtain required reviews]
    Wait --> Approval
    Approval -->|Yes| Confirm[Review payload and explicitly confirm execution]
    Confirm --> MCP[Execute allowed MCP operation]
    MCP --> History[Record execution result and durable history]
    MCP --> Unknown{External result uncertain?}
    Unknown -->|Yes| Reconcile[Inspect external system before any retry]
    Unknown -->|No| Done[Review result]
```

Encoder is disabled by default and documented as a trusted loopback development MVP. It can prepare and validate data without executing an external operation. AI suggestions must be inspected and applied explicitly; execution requires approvals and explicit payload confirmation. If the external outcome is uncertain, inspect the external system before retrying. See the [Encoder guide](../auditcounter_django/encoder/README.md).

## Practical example

1. A company uploads a supplier invoice and delivery receipt, extracts and reviews their text, and routes them to AP. Alternatively, it imports the corresponding records from a configured PostgreSQL source.
2. AuditCounter saves the supplier invoice and delivery receipt, including available line items and source links. The company purchase order is also present.
3. A user groups the documents into a case, reviews proposed line matches, and allocates quantities. If the order says 50 units but the receipt supports 48, the evaluation can retain the difference and create findings for review.
4. The user reviews the evidence, investigates and, if appropriate, creates a supplier claim. A supplier credit is recorded and verified; only an explicit application affects the invoice settlement. The claim can then be closed if its required evidence is satisfied.
5. A later payment allocation and cleared payment contribute to settlement independently of the document match. Dashboards and the timeline show the current state and preserved history.

## Operational boundaries

- Provider calls, reviews and imports can run within web requests; the project documentation describes no background queue or automatic retry. Large operations need suitable timeouts.
- The README states that the workspaces do not provide application-level authentication or organization isolation. Restrict access at the hosting layer.
- Several newer workflows are present in the current workspace and require their corresponding migrations on the target application database. This guide does not assert that they are deployed or enabled.
- Key implementation references: [document routing](../auditcounter_django/router/README.md), [AP/AR workflow](../auditcounter_django/accounts_receivable/README.md), [database migration](../auditcounter_django/accounts_receivable/DATABASE_MIGRATION.md), [Encoder](../auditcounter_django/encoder/README.md), and [new workflow implementation report](mvp-implementation-report.md).
