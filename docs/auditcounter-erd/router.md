# router ER diagram

Tables owned by `router` include all local fields. Referenced tables from other apps show only their primary key; see the [diagram index](../auditcounter-django-erd.md) for their full definitions. Relationships are shown in the diagram of the app that owns the foreign key.

```mermaid
erDiagram
    document_extraction_docextractionlog {
        AutoField doc_log_no PK
    }
    document_extraction_document {
        AutoField document_no PK
    }
    document_extraction_llmextractionlog {
        AutoField llm_log_no PK
    }
    encoder_mcpconnection {
        BigAutoField id PK
    }
    router_documentroute {
        JSONField encoder_config
        AutoField route_no PK
        ForeignKey routing_log_id FK
        ForeignKey destination_id FK
        CharField processing_status
        TextField processing_error
        DateTimeField processed_at
        TextField reason
        DecimalField confidence
        CharField review_status
        TextField review_notes
        DateTimeField created_at
        DateTimeField updated_at
    }
    router_llmroutinglog {
        AutoField routing_log_no PK
        UUIDField request_id
        ForeignKey source_document_id FK
        TextField input_text
        ForeignKey source_text_log_id FK
        ForeignKey source_llm_log_id FK
        CharField source_review_status
        BooleanField confirmed_unapproved
        CharField source_revision
        TextField prompt_text
        JSONField rules_snapshot
        CharField provider
        CharField model_name
        CharField status
        TextField response_text
        JSONField request_payload
        JSONField response_payload
        PositiveIntegerField input_tokens
        PositiveIntegerField output_tokens
        PositiveIntegerField processing_time_ms
        TextField error_message
        BooleanField user_selected_accurate
        DateTimeField created_at
        DateTimeField updated_at
    }
    router_routingdestination {
        BooleanField is_deleted
        AutoField destination_no PK
        CharField name
        CharField module_name
        CharField target_model
        TextField description
        BooleanField is_active
        DateTimeField created_at
        DateTimeField updated_at
    }
    router_routingrule {
        ForeignKey encoder_connection_id FK
        CharField encoder_tool
        AutoField rule_no PK
        CharField name
        ForeignKey destination_id FK
        CharField document_type
        TextField instructions
        TextField examples
        BooleanField is_active
        DateTimeField created_at
        DateTimeField updated_at
    }
    router_llmroutinglog ||--o{ router_documentroute : "routing_log"
    router_routingdestination ||--o{ router_documentroute : "destination"
    document_extraction_document ||--o{ router_llmroutinglog : "source_document"
    document_extraction_docextractionlog o|--o{ router_llmroutinglog : "source_text_log"
    document_extraction_llmextractionlog o|--o{ router_llmroutinglog : "source_llm_log"
    encoder_mcpconnection o|--o{ router_routingrule : "encoder_connection"
    router_routingdestination ||--o{ router_routingrule : "destination"
```
