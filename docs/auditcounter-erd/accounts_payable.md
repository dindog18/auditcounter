# accounts_payable ER diagram

Tables owned by `accounts_payable` include all local fields. Referenced tables from other apps show only their primary key; see the [diagram index](../auditcounter-django-erd.md) for their full definitions. Relationships are shown in the diagram of the app that owns the foreign key.

```mermaid
erDiagram
    accounts_payable_companypayment {
        AutoField company_payment_no PK
        ForeignKey supplier_id FK
        CharField payment_reference_no
        DateField payment_date
        DateField posting_date
        CharField payment_method
        CharField bank_reference_no
        CharField currency
        DecimalField amount_paid
        DecimalField withholding_tax_amount
        DecimalField discount_taken
        CharField payment_status
        DateTimeField cleared_at
        DateTimeField reversed_at
        TextField reversal_reason
        ForeignKey proof_of_payment_id FK
        ForeignKey source_table_id FK
        JSONField source_record_key
        DateTimeField imported_at
        ForeignKey source_llm_log_id FK
        ForeignKey source_text_log_id FK
        DateTimeField created_at
        DateTimeField updated_at
        ForeignKey source_document_id FK
        ForeignKey source_database_id FK
        TextField payment_metadata
        TextField payment_context
    }
    accounts_payable_companypurchaseorder {
        AutoField company_purchase_order PK
        ForeignKey supplier_id FK
        CharField po_reference_no UK
        DateField order_date
        DateField expected_delivery_date
        CharField currency
        DecimalField subtotal
        DecimalField discount_amount
        DecimalField tax_amount
        DecimalField total_amount
        DecimalField other_charges
        CharField status
        ForeignKey source_table_id FK
        JSONField source_record_key
        DateTimeField imported_at
        ForeignKey source_llm_log_id FK
        ForeignKey source_text_log_id FK
        DateTimeField created_at
        DateTimeField updated_at
        ForeignKey source_document_id FK
        ForeignKey source_database_id FK
        TextField purchase_order_metadata
        TextField purchase_order_context
    }
    accounts_payable_companypurchaseorderline {
        BigAutoField id PK
        PositiveIntegerField line_no
        CharField item_code
        TextField description
        CharField unit_of_measure
        DecimalField quantity_ordered
        DecimalField unit_price
        DecimalField discount_amount
        DecimalField tax_amount
        DecimalField line_total
        ForeignKey purchase_order_id FK
    }
    accounts_payable_databaseimportrun {
        BigAutoField id PK
        ForeignKey configuration_id FK
        UUIDField request_id UK
        JSONField configuration_snapshot
        CharField status
        JSONField result
        DateTimeField created_at
        DateTimeField finished_at
    }
    accounts_payable_documentmatch {
        BigAutoField id PK
        DecimalField matched_quantity
        CharField match_status
        JSONField sku_identity_snapshot
        TextField notes
        DateTimeField created_at
        ForeignKey transaction_id FK
        ForeignKey purchase_order_line_id FK
        ForeignKey delivery_receipt_line_id FK
        ForeignKey invoice_line_id FK
    }
    accounts_payable_extractionconfiguration {
        BigAutoField id PK
        CharField name
        TextField description
        CharField target_entity
        CharField source_type
        ForeignKey supplier_id FK
        ForeignKey database_source_id FK
        ForeignKey source_table_id FK
        ForeignKey line_source_table_id FK
        JSONField source_schema_snapshot
        JSONField source_key_fields
        JSONField field_mappings
        JSONField line_item_mappings
        JSONField line_join_fields
        JSONField relation_lookups
        CharField document_type
        TextField extraction_context
        JSONField field_instructions
        JSONField line_field_instructions
        TextField line_item_context
        TextField sample_text
        JSONField encoding_rules
        JSONField setup_data
        JSONField assistant_messages
        JSONField assistant_proposal
        CharField status
        PositiveIntegerField revision
        JSONField submitted_snapshot
        DateTimeField submitted_at
        ForeignKey submitted_by_id FK
        DateTimeField created_at
        DateTimeField updated_at
    }
    accounts_payable_llmextractionlog {
        AutoField llm_log_no PK
        ForeignKey configuration_id FK
        ForeignKey routing_route_id FK
        PositiveIntegerField configuration_revision
        CharField target_entity
        CharField source_type
        CharField purpose
        ForeignKey supplier_id FK
        ForeignKey purchase_order_id FK
        ForeignKey delivery_receipt_id FK
        ForeignKey sales_invoice_id FK
        ForeignKey payment_id FK
        ForeignKey fk_document_no_id FK
        ForeignKey source_llm_log_id FK
        CharField provider
        CharField model_name
        CharField status
        JSONField configuration_snapshot
        JSONField request_payload
        JSONField response_payload
        TextField markdown_text
        PositiveIntegerField input_tokens
        PositiveIntegerField output_tokens
        PositiveIntegerField processing_time_ms
        TextField error_message
        BooleanField is_simulated
        BooleanField user_selected_accurate
        ForeignKey reviewed_by_id FK
        DateTimeField reviewed_at
        JSONField review_metadata
        DateTimeField created_at
        DateTimeField updated_at
    }
    accounts_payable_paymentallocation {
        BigAutoField id PK
        DecimalField cash_amount
        DecimalField withholding_tax_amount
        DecimalField discount_amount
        DateTimeField created_at
        ForeignKey payment_id FK
        ForeignKey invoice_id FK
    }
    accounts_payable_supplier {
        AutoField supplier_no PK
        CharField supplier_code UK
        CharField supplier_name
        CharField tax_identification_no
        TextField billing_address
        CharField contact_person
        CharField email
        CharField phone
        PositiveIntegerField payment_terms_days
        BooleanField is_active
        TextField llm_context
    }
    accounts_payable_suppliercreditapplication {
        BigAutoField id PK
        ForeignKey credit_id FK
        ForeignKey invoice_id FK
        DecimalField amount
        CharField request_key
        DateField application_date
        TextField notes
        DateTimeField created_at
    }
    accounts_payable_suppliercreditnote {
        BigAutoField id PK
        ForeignKey supplier_id FK
        CharField reference
        DateField issue_date
        CharField currency
        DecimalField credit_amount
        CharField status
        ForeignKey source_document_id FK
        ForeignKey source_database_id FK
        ForeignKey source_table_id FK
        JSONField source_record_key
        TextField verification_notes
        DateTimeField verified_at
        DateTimeField created_at
        DateTimeField updated_at
    }
    accounts_payable_suppliercreditreversal {
        BigAutoField id PK
        OneToOneField application_id FK
        TextField reason
        DateTimeField created_at
    }
    accounts_payable_supplierdeliveryreceipt {
        AutoField supplier_delivery_receipt_no PK
        ForeignKey supplier_id FK
        CharField dr_reference_no
        DateField delivery_date
        DateField received_date
        CharField received_by
        ForeignKey receiving_evidence_id FK
        CharField delivery_location
        CharField receipt_status
        BooleanField has_discrepancy
        ForeignKey source_table_id FK
        JSONField source_record_key
        DateTimeField imported_at
        ForeignKey source_llm_log_id FK
        ForeignKey source_text_log_id FK
        DateTimeField created_at
        DateTimeField updated_at
        ForeignKey source_document_id FK
        ForeignKey source_database_id FK
        JSONField received_items
        TextField delivery_receipt_metadata
        TextField delivery_receipt_context
    }
    accounts_payable_supplierdeliveryreceiptline {
        BigAutoField id PK
        PositiveIntegerField line_no
        CharField item_code
        TextField description
        CharField unit_of_measure
        DecimalField quantity_stated
        DecimalField quantity_received
        DecimalField quantity_accepted
        DecimalField quantity_rejected
        ForeignKey delivery_receipt_id FK
    }
    accounts_payable_suppliersalesinvoice {
        AutoField supplier_sales_invoice_no PK
        ForeignKey supplier_id FK
        CharField invoice_reference_no
        DateField invoice_date
        DateField due_date
        CharField currency
        DecimalField subtotal
        DecimalField discount_amount
        DecimalField tax_amount
        DecimalField other_charges
        DecimalField total_amount
        CharField invoice_status
        CharField payment_status
        TextField notes
        ForeignKey source_table_id FK
        JSONField source_record_key
        DateTimeField imported_at
        ForeignKey source_llm_log_id FK
        ForeignKey source_text_log_id FK
        DateTimeField created_at
        DateTimeField updated_at
        ForeignKey source_document_id FK
        ForeignKey source_database_id FK
        TextField invoice_metadata
        TextField invoice_context
    }
    accounts_payable_suppliersalesinvoiceline {
        BigAutoField id PK
        PositiveIntegerField line_no
        CharField item_code
        TextField description
        CharField unit_of_measure
        DecimalField quantity_invoiced
        DecimalField unit_price
        DecimalField discount_amount
        DecimalField tax_amount
        DecimalField line_total
        ForeignKey invoice_id FK
    }
    accounts_payable_supplierstatement {
        BigAutoField id PK
        ForeignKey supplier_id FK
        CharField reference
        DateField statement_date
        DateField period_start
        CharField currency
        DecimalField opening_balance
        DecimalField closing_balance
        ForeignKey source_document_id FK
        ForeignKey ap_transaction_id FK
        CharField reconciliation_status
        DateTimeField created_at
        DateTimeField updated_at
    }
    accounts_payable_supplierstatementevaluation {
        BigAutoField id PK
        ForeignKey statement_id FK
        JSONField result
        DateTimeField created_at
    }
    accounts_payable_supplierstatementline {
        BigAutoField id PK
        ForeignKey statement_id FK
        PositiveIntegerField line_no
        CharField reference
        DateField transaction_date
        CharField kind
        DecimalField amount
        CharField review_decision
        TextField review_notes
        DateTimeField reviewed_at
    }
    accounts_payable_supplierstatementmatch {
        BigAutoField id PK
        ForeignKey statement_id FK
        ForeignKey line_id FK
        ForeignKey invoice_id FK
        ForeignKey payment_id FK
        ForeignKey credit_id FK
        BooleanField active
        TextField notes
        DateTimeField created_at
        DateTimeField superseded_at
    }
    accounts_payable_transaction {
        AutoField transaction_no PK
        ForeignKey supplier_id FK
        DateField transaction_date
        CharField currency
        CharField reconciliation_status
        DecimalField total_discrepancy_amount
        DateTimeField reconciled_at
        DateTimeField created_at
        DateTimeField updated_at
        TextField notes
    }
    accounts_payable_transaction_delivery_receipts {
        BigAutoField id PK
        ForeignKey transaction_id FK
        ForeignKey supplierdeliveryreceipt_id FK
    }
    accounts_payable_transaction_purchase_orders {
        BigAutoField id PK
        ForeignKey transaction_id FK
        ForeignKey companypurchaseorder_id FK
    }
    accounts_payable_transaction_sales_invoices {
        BigAutoField id PK
        ForeignKey transaction_id FK
        ForeignKey suppliersalesinvoice_id FK
    }
    auth_user {
        AutoField id PK
    }
    db_extraction_databasesource {
        BigAutoField id PK
    }
    db_extraction_databasetable {
        BigAutoField id PK
    }
    document_extraction_docextractionlog {
        AutoField doc_log_no PK
    }
    document_extraction_document {
        AutoField document_no PK
    }
    document_extraction_llmextractionlog {
        AutoField llm_log_no PK
    }
    router_documentroute {
        AutoField route_no PK
    }
    accounts_payable_supplier o|--o{ accounts_payable_companypayment : "supplier"
    document_extraction_document o|--o{ accounts_payable_companypayment : "proof_of_payment"
    db_extraction_databasetable o|--o{ accounts_payable_companypayment : "source_table"
    document_extraction_llmextractionlog o|--o{ accounts_payable_companypayment : "source_llm_log"
    document_extraction_docextractionlog o|--o{ accounts_payable_companypayment : "source_text_log"
    document_extraction_document o|--o{ accounts_payable_companypayment : "source_document"
    db_extraction_databasesource o|--o{ accounts_payable_companypayment : "source_database"
    accounts_payable_supplier ||--o{ accounts_payable_companypurchaseorder : "supplier"
    db_extraction_databasetable o|--o{ accounts_payable_companypurchaseorder : "source_table"
    document_extraction_llmextractionlog o|--o{ accounts_payable_companypurchaseorder : "source_llm_log"
    document_extraction_docextractionlog o|--o{ accounts_payable_companypurchaseorder : "source_text_log"
    document_extraction_document o|--o{ accounts_payable_companypurchaseorder : "source_document"
    db_extraction_databasesource o|--o{ accounts_payable_companypurchaseorder : "source_database"
    accounts_payable_companypurchaseorder ||--o{ accounts_payable_companypurchaseorderline : "purchase_order"
    accounts_payable_extractionconfiguration o|--o{ accounts_payable_databaseimportrun : "configuration"
    accounts_payable_transaction ||--o{ accounts_payable_documentmatch : "transaction"
    accounts_payable_companypurchaseorderline o|--o{ accounts_payable_documentmatch : "purchase_order_line"
    accounts_payable_supplierdeliveryreceiptline o|--o{ accounts_payable_documentmatch : "delivery_receipt_line"
    accounts_payable_suppliersalesinvoiceline ||--o{ accounts_payable_documentmatch : "invoice_line"
    accounts_payable_supplier o|--o{ accounts_payable_extractionconfiguration : "supplier"
    db_extraction_databasesource o|--o{ accounts_payable_extractionconfiguration : "database_source"
    db_extraction_databasetable o|--o{ accounts_payable_extractionconfiguration : "source_table"
    db_extraction_databasetable o|--o{ accounts_payable_extractionconfiguration : "line_source_table"
    auth_user o|--o{ accounts_payable_extractionconfiguration : "submitted_by"
    accounts_payable_extractionconfiguration o|--o{ accounts_payable_llmextractionlog : "configuration"
    router_documentroute o|--o{ accounts_payable_llmextractionlog : "routing_route"
    accounts_payable_supplier o|--o{ accounts_payable_llmextractionlog : "supplier"
    accounts_payable_companypurchaseorder o|--o{ accounts_payable_llmextractionlog : "purchase_order"
    accounts_payable_supplierdeliveryreceipt o|--o{ accounts_payable_llmextractionlog : "delivery_receipt"
    accounts_payable_suppliersalesinvoice o|--o{ accounts_payable_llmextractionlog : "sales_invoice"
    accounts_payable_companypayment o|--o{ accounts_payable_llmextractionlog : "payment"
    document_extraction_document o|--o{ accounts_payable_llmextractionlog : "fk_document_no"
    document_extraction_llmextractionlog o|--o{ accounts_payable_llmextractionlog : "source_llm_log"
    auth_user o|--o{ accounts_payable_llmextractionlog : "reviewed_by"
    accounts_payable_companypayment ||--o{ accounts_payable_paymentallocation : "payment"
    accounts_payable_suppliersalesinvoice ||--o{ accounts_payable_paymentallocation : "invoice"
    accounts_payable_suppliercreditnote ||--o{ accounts_payable_suppliercreditapplication : "credit"
    accounts_payable_suppliersalesinvoice ||--o{ accounts_payable_suppliercreditapplication : "invoice"
    accounts_payable_supplier ||--o{ accounts_payable_suppliercreditnote : "supplier"
    document_extraction_document o|--o{ accounts_payable_suppliercreditnote : "source_document"
    db_extraction_databasesource o|--o{ accounts_payable_suppliercreditnote : "source_database"
    db_extraction_databasetable o|--o{ accounts_payable_suppliercreditnote : "source_table"
    accounts_payable_suppliercreditapplication ||--o| accounts_payable_suppliercreditreversal : "application"
    accounts_payable_supplier o|--o{ accounts_payable_supplierdeliveryreceipt : "supplier"
    document_extraction_document o|--o{ accounts_payable_supplierdeliveryreceipt : "receiving_evidence"
    db_extraction_databasetable o|--o{ accounts_payable_supplierdeliveryreceipt : "source_table"
    document_extraction_llmextractionlog o|--o{ accounts_payable_supplierdeliveryreceipt : "source_llm_log"
    document_extraction_docextractionlog o|--o{ accounts_payable_supplierdeliveryreceipt : "source_text_log"
    document_extraction_document o|--o{ accounts_payable_supplierdeliveryreceipt : "source_document"
    db_extraction_databasesource o|--o{ accounts_payable_supplierdeliveryreceipt : "source_database"
    accounts_payable_supplierdeliveryreceipt ||--o{ accounts_payable_supplierdeliveryreceiptline : "delivery_receipt"
    accounts_payable_supplier o|--o{ accounts_payable_suppliersalesinvoice : "supplier"
    db_extraction_databasetable o|--o{ accounts_payable_suppliersalesinvoice : "source_table"
    document_extraction_llmextractionlog o|--o{ accounts_payable_suppliersalesinvoice : "source_llm_log"
    document_extraction_docextractionlog o|--o{ accounts_payable_suppliersalesinvoice : "source_text_log"
    document_extraction_document o|--o{ accounts_payable_suppliersalesinvoice : "source_document"
    db_extraction_databasesource o|--o{ accounts_payable_suppliersalesinvoice : "source_database"
    accounts_payable_suppliersalesinvoice ||--o{ accounts_payable_suppliersalesinvoiceline : "invoice"
    accounts_payable_supplier ||--o{ accounts_payable_supplierstatement : "supplier"
    document_extraction_document ||--o{ accounts_payable_supplierstatement : "source_document"
    accounts_payable_transaction o|--o{ accounts_payable_supplierstatement : "ap_transaction"
    accounts_payable_supplierstatement ||--o{ accounts_payable_supplierstatementevaluation : "statement"
    accounts_payable_supplierstatement ||--o{ accounts_payable_supplierstatementline : "statement"
    accounts_payable_supplierstatement ||--o{ accounts_payable_supplierstatementmatch : "statement"
    accounts_payable_supplierstatementline ||--o{ accounts_payable_supplierstatementmatch : "line"
    accounts_payable_suppliersalesinvoice o|--o{ accounts_payable_supplierstatementmatch : "invoice"
    accounts_payable_companypayment o|--o{ accounts_payable_supplierstatementmatch : "payment"
    accounts_payable_suppliercreditnote o|--o{ accounts_payable_supplierstatementmatch : "credit"
    accounts_payable_supplier o|--o{ accounts_payable_transaction : "supplier"
    accounts_payable_transaction ||--o{ accounts_payable_transaction_delivery_receipts : "transaction"
    accounts_payable_supplierdeliveryreceipt ||--o{ accounts_payable_transaction_delivery_receipts : "supplierdeliveryreceipt"
    accounts_payable_transaction ||--o{ accounts_payable_transaction_purchase_orders : "transaction"
    accounts_payable_companypurchaseorder ||--o{ accounts_payable_transaction_purchase_orders : "companypurchaseorder"
    accounts_payable_transaction ||--o{ accounts_payable_transaction_sales_invoices : "transaction"
    accounts_payable_suppliersalesinvoice ||--o{ accounts_payable_transaction_sales_invoices : "suppliersalesinvoice"
```
