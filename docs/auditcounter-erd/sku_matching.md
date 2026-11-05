# sku_matching ER diagram

Tables owned by `sku_matching` include all local fields. Referenced tables from other apps show only their primary key; see the [diagram index](../auditcounter-django-erd.md) for their full definitions. Relationships are shown in the diagram of the app that owns the foreign key.

```mermaid
erDiagram
    accounts_payable_supplier {
        AutoField supplier_no PK
    }
    accounts_receivable_customer {
        AutoField customer_no PK
    }
    sku_matching_skualias {
        BigAutoField id PK
        CharField scope
        ForeignKey supplier_id FK
        ForeignKey customer_id FK
        CharField source_system
        CharField source_item_code
        CharField normalized_source_code
        CharField canonical_item_code
        CharField normalized_canonical_code
        TextField source_description
        TextField canonical_description
        CharField unit_of_measure
        CharField normalized_unit
        JSONField source_reference
        JSONField canonical_reference
        JSONField source_snapshot
        JSONField canonical_snapshot
        CharField status
        TextField suggestion_reason
        TextField approval_notes
        DateTimeField approved_at
        JSONField history
        DateTimeField created_at
        DateTimeField updated_at
    }
    sku_matching_skusuggestionattempt {
        BigAutoField id PK
        CharField scope
        ForeignKey supplier_id FK
        ForeignKey customer_id FK
        ForeignKey alias_id FK
        CharField source_system
        JSONField source_reference
        JSONField input_product
        JSONField candidates
        CharField provider
        CharField model_name
        JSONField request_payload
        JSONField response_payload
        JSONField suggested_target
        CharField status
        JSONField validation_errors
        PositiveIntegerField processing_time_ms
        JSONField usage
        DateTimeField created_at
    }
    accounts_payable_supplier o|--o{ sku_matching_skualias : "supplier"
    accounts_receivable_customer o|--o{ sku_matching_skualias : "customer"
    accounts_payable_supplier o|--o{ sku_matching_skusuggestionattempt : "supplier"
    accounts_receivable_customer o|--o{ sku_matching_skusuggestionattempt : "customer"
    sku_matching_skualias o|--o{ sku_matching_skusuggestionattempt : "alias"
```
