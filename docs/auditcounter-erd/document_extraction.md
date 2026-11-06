# document_extraction ER diagram

Tables owned by `document_extraction` include all local fields. Referenced tables from other apps show only their primary key; see the [diagram index](../auditcounter-django-erd.md) for their full definitions. Relationships are shown in the diagram of the app that owns the foreign key.

```mermaid
erDiagram
    document_extraction_batch {
        AutoField batch_no PK
        DateTimeField created_at
        DateTimeField updated_at
    }
    document_extraction_docextractionlog {
        AutoField doc_log_no PK
        ForeignKey fk_document_no_id FK
        TextField markdown_text
        TextField error_message
        BooleanField user_selected_accurate
        DateTimeField created_at
        DateTimeField updated_at
    }
    document_extraction_document {
        AutoField document_no PK
        ForeignKey fk_batch_no_id FK
        CharField file_name
        CharField mime_type
        CharField document_type
        CharField storage_path
        CharField processing_status
        CharField review_status
        DateTimeField created_at
        DateTimeField updated_at
    }
    document_extraction_llmextractionlog {
        AutoField llm_log_no PK
        ForeignKey fk_document_no_id FK
        CharField provider
        CharField model_name
        CharField status
        TextField markdown_text
        PositiveIntegerField input_tokens
        PositiveIntegerField output_tokens
        PositiveIntegerField processing_time_ms
        TextField error_message
        BooleanField user_selected_accurate
        DateTimeField created_at
        DateTimeField updated_at
    }
    document_extraction_workspacesetuppreferences {
        BigAutoField id PK
        JSONField active_modules
        DateTimeField updated_at
    }
    document_extraction_document ||--o{ document_extraction_docextractionlog : "fk_document_no"
    document_extraction_batch o|--o{ document_extraction_document : "fk_batch_no"
    document_extraction_document ||--o{ document_extraction_llmextractionlog : "fk_document_no"
```
