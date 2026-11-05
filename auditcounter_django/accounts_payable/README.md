# Accounts payable

AP owns supplier accounts, reconciliation and extraction orchestration. Each
AP document has its own Django app and document logic. See the
[document app architecture and migration guide](../../docs/accounting-document-apps.md).

Cross-document matching and settlement rules live in `services/reconciliation.py`.
The workspace, configuration, extraction and import services are shared with AR
through an explicit module argument. See the [AP/AR backend guide](../accounts_receivable/README.md).

## PO reconciliation and deductions

Use **Reconciliation** for the automatic PO-led workflow and **Deductions** for
Defective, Pull Out, Support, Credit Memo, and other adjustments. See the
[workflow and migration guide](../../docs/accounting-reconciliation.md).
