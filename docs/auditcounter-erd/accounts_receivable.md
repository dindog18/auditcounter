# accounts_receivable ER diagram

Tables owned by `accounts_receivable` include all local fields. Referenced tables from other apps show only their primary key; see the [diagram index](../auditcounter-django-erd.md) for their full definitions. Relationships are shown in the diagram of the app that owns the foreign key.

```mermaid
erDiagram
    accounts_receivable_companydeliveryreceipt {
        AutoField company_delivery_receipt_no PK
        ForeignKey customer_id FK
        CharField dr_reference_no
        DateField delivery_date
        TextField delivery_address
        CharField received_by
        DateTimeField received_at
        CharField delivery_status
        ForeignKey proof_of_delivery_id FK
        ForeignKey source_table_id FK
        JSONField source_record_key
        DateTimeField imported_at
        ForeignKey source_llm_log_id FK
        ForeignKey source_text_log_id FK
        DateTimeField created_at
        DateTimeField updated_at
        ForeignKey source_document_id FK
        ForeignKey source_database_id FK
        TextField delivery_receipt_metadata
        TextField delivery_receipt_context
    }
    accounts_receivable_companydeliveryreceiptline {
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
    accounts_receivable_companysalesinvoice {
        AutoField company_sales_invoice_no PK
        ForeignKey customer_id FK
        CharField invoice_reference_no
        DateField invoice_date
        DateField due_date
        CharField currency
        DecimalField subtotal
        DecimalField discount_amount
        DecimalField tax_amount
        DecimalField total_amount
        CharField payment_status
        CharField invoice_status
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
    accounts_receivable_companysalesinvoiceline {
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
    accounts_receivable_customer {
        AutoField customer_no PK
        CharField customer_code UK
        CharField customer_name
        CharField tax_identification_no
        TextField billing_address
        TextField shipping_address
        CharField contact_person
        CharField email
        CharField phone
        DecimalField credit_limit
        PositiveIntegerField payment_terms_days
        BooleanField is_active
        TextField llm_context
    }
    accounts_receivable_customerdeduction {
        BigAutoField id PK
        ForeignKey customer_id FK
        ForeignKey invoice_id FK
        ForeignKey payment_id FK
        CharField reference
        CharField reason_code
        DecimalField claimed_amount
        DecimalField accepted_amount
        CharField currency
        CharField status
        ForeignKey source_document_id FK
        TextField resolution_notes
        DateTimeField created_at
        DateTimeField updated_at
    }
    accounts_receivable_customerpayment {
        AutoField customer_payment_no PK
        ForeignKey customer_id FK
        CharField payment_reference_no
        DateField payment_date
        DateField posting_date
        CharField payment_method
        CharField bank_reference_no
        CharField currency
        DecimalField amount_received
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
    accounts_receivable_customerpurchaseorder {
        AutoField customer_purchase_order_no PK
        ForeignKey customer_id FK
        CharField po_reference_no
        DateField order_date
        DateField expected_delivery_date
        CharField currency
        DecimalField subtotal
        DecimalField discount_amount
        DecimalField tax_amount
        DecimalField total_amount
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
    accounts_receivable_customerpurchaseorderline {
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
    accounts_receivable_databaseimportrun {
        BigAutoField id PK
        ForeignKey configuration_id FK
        UUIDField request_id UK
        JSONField configuration_snapshot
        CharField status
        JSONField result
        DateTimeField created_at
        DateTimeField finished_at
    }
    accounts_receivable_deductionapplication {
        BigAutoField id PK
        ForeignKey deduction_id FK
        DecimalField amount
        CharField request_key
        TextField notes
        DateTimeField created_at
    }
    accounts_receivable_deductionobservation {
        BigAutoField id PK
        ForeignKey deduction_id FK
        JSONField state
        DateTimeField created_at
    }
    accounts_receivable_deductionreversal {
        BigAutoField id PK
        OneToOneField application_id FK
        TextField reason
        DateTimeField created_at
    }
    accounts_receivable_documentmatch {
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
    accounts_receivable_extractionconfiguration {
        BigAutoField id PK
        CharField name
        TextField description
        CharField target_entity
        CharField source_type
        ForeignKey customer_id FK
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
    accounts_receivable_llmextractionlog {
        AutoField llm_log_no PK
        ForeignKey configuration_id FK
        ForeignKey routing_route_id FK
        PositiveIntegerField configuration_revision
        CharField target_entity
        CharField source_type
        CharField purpose
        ForeignKey customer_id FK
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
    accounts_receivable_paymentallocation {
        BigAutoField id PK
        DecimalField cash_amount
        DecimalField withholding_tax_amount
        DecimalField discount_amount
        DateTimeField created_at
        ForeignKey payment_id FK
        ForeignKey invoice_id FK
    }
    accounts_receivable_transaction {
        AutoField transaction_no PK
        ForeignKey customer_id FK
        DateField transaction_date
        CharField currency
        CharField reconciliation_status
        DecimalField total_discrepancy_amount
        DateTimeField reconciled_at
        DateTimeField created_at
        DateTimeField updated_at
        TextField notes
    }
    accounts_receivable_transaction_delivery_receipts {
        BigAutoField id PK
        ForeignKey transaction_id FK
        ForeignKey companydeliveryreceipt_id FK
    }
    accounts_receivable_transaction_purchase_orders {
        BigAutoField id PK
        ForeignKey transaction_id FK
        ForeignKey customerpurchaseorder_id FK
    }
    accounts_receivable_transaction_sales_invoices {
        BigAutoField id PK
        ForeignKey transaction_id FK
        ForeignKey companysalesinvoice_id FK
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
    accounts_receivable_customer o|--o{ accounts_receivable_companydeliveryreceipt : "customer"
    document_extraction_document o|--o{ accounts_receivable_companydeliveryreceipt : "proof_of_delivery"
    db_extraction_databasetable o|--o{ accounts_receivable_companydeliveryreceipt : "source_table"
    document_extraction_llmextractionlog o|--o{ accounts_receivable_companydeliveryreceipt : "source_llm_log"
    document_extraction_docextractionlog o|--o{ accounts_receivable_companydeliveryreceipt : "source_text_log"
    document_extraction_document o|--o{ accounts_receivable_companydeliveryreceipt : "source_document"
    db_extraction_databasesource o|--o{ accounts_receivable_companydeliveryreceipt : "source_database"
    accounts_receivable_companydeliveryreceipt ||--o{ accounts_receivable_companydeliveryreceiptline : "delivery_receipt"
    accounts_receivable_customer o|--o{ accounts_receivable_companysalesinvoice : "customer"
    db_extraction_databasetable o|--o{ accounts_receivable_companysalesinvoice : "source_table"
    document_extraction_llmextractionlog o|--o{ accounts_receivable_companysalesinvoice : "source_llm_log"
    document_extraction_docextractionlog o|--o{ accounts_receivable_companysalesinvoice : "source_text_log"
    document_extraction_document o|--o{ accounts_receivable_companysalesinvoice : "source_document"
    db_extraction_databasesource o|--o{ accounts_receivable_companysalesinvoice : "source_database"
    accounts_receivable_companysalesinvoice ||--o{ accounts_receivable_companysalesinvoiceline : "invoice"
    accounts_receivable_customer ||--o{ accounts_receivable_customerdeduction : "customer"
    accounts_receivable_companysalesinvoice ||--o{ accounts_receivable_customerdeduction : "invoice"
    accounts_receivable_customerpayment o|--o{ accounts_receivable_customerdeduction : "payment"
    document_extraction_document ||--o{ accounts_receivable_customerdeduction : "source_document"
    accounts_receivable_customer o|--o{ accounts_receivable_customerpayment : "customer"
    document_extraction_document o|--o{ accounts_receivable_customerpayment : "proof_of_payment"
    db_extraction_databasetable o|--o{ accounts_receivable_customerpayment : "source_table"
    document_extraction_llmextractionlog o|--o{ accounts_receivable_customerpayment : "source_llm_log"
    document_extraction_docextractionlog o|--o{ accounts_receivable_customerpayment : "source_text_log"
    document_extraction_document o|--o{ accounts_receivable_customerpayment : "source_document"
    db_extraction_databasesource o|--o{ accounts_receivable_customerpayment : "source_database"
    accounts_receivable_customer ||--o{ accounts_receivable_customerpurchaseorder : "customer"
    db_extraction_databasetable o|--o{ accounts_receivable_customerpurchaseorder : "source_table"
    document_extraction_llmextractionlog o|--o{ accounts_receivable_customerpurchaseorder : "source_llm_log"
    document_extraction_docextractionlog o|--o{ accounts_receivable_customerpurchaseorder : "source_text_log"
    document_extraction_document o|--o{ accounts_receivable_customerpurchaseorder : "source_document"
    db_extraction_databasesource o|--o{ accounts_receivable_customerpurchaseorder : "source_database"
    accounts_receivable_customerpurchaseorder ||--o{ accounts_receivable_customerpurchaseorderline : "purchase_order"
    accounts_receivable_extractionconfiguration o|--o{ accounts_receivable_databaseimportrun : "configuration"
    accounts_receivable_customerdeduction ||--o{ accounts_receivable_deductionapplication : "deduction"
    accounts_receivable_customerdeduction ||--o{ accounts_receivable_deductionobservation : "deduction"
    accounts_receivable_deductionapplication ||--o| accounts_receivable_deductionreversal : "application"
    accounts_receivable_transaction ||--o{ accounts_receivable_documentmatch : "transaction"
    accounts_receivable_customerpurchaseorderline o|--o{ accounts_receivable_documentmatch : "purchase_order_line"
    accounts_receivable_companydeliveryreceiptline o|--o{ accounts_receivable_documentmatch : "delivery_receipt_line"
    accounts_receivable_companysalesinvoiceline ||--o{ accounts_receivable_documentmatch : "invoice_line"
    accounts_receivable_customer o|--o{ accounts_receivable_extractionconfiguration : "customer"
    db_extraction_databasesource o|--o{ accounts_receivable_extractionconfiguration : "database_source"
    db_extraction_databasetable o|--o{ accounts_receivable_extractionconfiguration : "source_table"
    db_extraction_databasetable o|--o{ accounts_receivable_extractionconfiguration : "line_source_table"
    auth_user o|--o{ accounts_receivable_extractionconfiguration : "submitted_by"
    accounts_receivable_extractionconfiguration o|--o{ accounts_receivable_llmextractionlog : "configuration"
    router_documentroute o|--o{ accounts_receivable_llmextractionlog : "routing_route"
    accounts_receivable_customer o|--o{ accounts_receivable_llmextractionlog : "customer"
    accounts_receivable_customerpurchaseorder o|--o{ accounts_receivable_llmextractionlog : "purchase_order"
    accounts_receivable_companydeliveryreceipt o|--o{ accounts_receivable_llmextractionlog : "delivery_receipt"
    accounts_receivable_companysalesinvoice o|--o{ accounts_receivable_llmextractionlog : "sales_invoice"
    accounts_receivable_customerpayment o|--o{ accounts_receivable_llmextractionlog : "payment"
    document_extraction_document o|--o{ accounts_receivable_llmextractionlog : "fk_document_no"
    document_extraction_llmextractionlog o|--o{ accounts_receivable_llmextractionlog : "source_llm_log"
    auth_user o|--o{ accounts_receivable_llmextractionlog : "reviewed_by"
    accounts_receivable_customerpayment ||--o{ accounts_receivable_paymentallocation : "payment"
    accounts_receivable_companysalesinvoice ||--o{ accounts_receivable_paymentallocation : "invoice"
    accounts_receivable_customer o|--o{ accounts_receivable_transaction : "customer"
    accounts_receivable_transaction ||--o{ accounts_receivable_transaction_delivery_receipts : "transaction"
    accounts_receivable_companydeliveryreceipt ||--o{ accounts_receivable_transaction_delivery_receipts : "companydeliveryreceipt"
    accounts_receivable_transaction ||--o{ accounts_receivable_transaction_purchase_orders : "transaction"
    accounts_receivable_customerpurchaseorder ||--o{ accounts_receivable_transaction_purchase_orders : "customerpurchaseorder"
    accounts_receivable_transaction ||--o{ accounts_receivable_transaction_sales_invoices : "transaction"
    accounts_receivable_companysalesinvoice ||--o{ accounts_receivable_transaction_sales_invoices : "companysalesinvoice"
```
