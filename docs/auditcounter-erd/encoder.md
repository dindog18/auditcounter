# encoder ER diagram

Tables owned by `encoder` include all local fields. Referenced tables from other apps show only their primary key; see the [diagram index](../auditcounter-django-erd.md) for their full definitions. Relationships are shown in the diagram of the app that owns the foreign key.

```mermaid
erDiagram
    encoder_encoderchatmessage {
        BigAutoField id PK
        PositiveIntegerField cycle
        CharField provider
        CharField model_name
        CharField status
        PositiveIntegerField input_tokens
        PositiveIntegerField output_tokens
        PositiveIntegerField processing_time_ms
        CharField error_code
        ForeignKey job_id FK
        CharField role
        TextField content
        JSONField proposal
        CharField base_revision
        CharField decision
        JSONField request_payload
        JSONField response_payload
        TextField error_message
        DateTimeField created_at
    }
    encoder_encoderexecution {
        BigAutoField id PK
        PositiveIntegerField cycle
        UUIDField request_id UK
        ForeignKey job_id FK
        ForeignKey connection_id FK
        CharField tool_name
        JSONField tool_schema
        JSONField connection_snapshot
        JSONField payload
        JSONField response
        CharField status
        TextField error_message
        DateTimeField reconciled_at
        DateTimeField confirmed_at
        DateTimeField finished_at
    }
    encoder_encoderjob {
        BigAutoField id PK
        PositiveIntegerField cycle
        OneToOneField route_id FK
        ForeignKey connection_id FK
        CharField tool_name
        JSONField tool_schema
        JSONField field_mappings
        JSONField prepared_payload
        JSONField validation_errors
        CharField status
        UUIDField idempotency_key
        CharField idempotency_field
        TextField last_error
        DateTimeField created_at
        DateTimeField updated_at
    }
    encoder_encodermapping {
        BigAutoField id PK
        ForeignKey connection_id FK
        CharField tool_name
        JSONField field_mappings
        CharField idempotency_field
        DateTimeField updated_at
    }
    encoder_encoderreset {
        BigAutoField id PK
        ForeignKey job_id FK
        PositiveIntegerField cycle
        JSONField snapshot
        DateTimeField created_at
    }
    encoder_mcpconnection {
        BigAutoField id PK
        CharField name UK
        CharField launch_profile
        CharField transport
        CharField server_url
        CharField bearer_token_env_var
        TextField http_headers
        JSONField env_http_headers
        CharField command
        JSONField arguments
        CharField working_directory
        JSONField environment_passthrough
        TextField environment
        BooleanField enabled
        PositiveIntegerField timeout_seconds
        JSONField approved_tools
        JSONField tools
        TextField discovery_error
        DateTimeField discovered_at
        DateTimeField created_at
        DateTimeField updated_at
    }
    router_documentroute {
        AutoField route_no PK
    }
    encoder_encoderjob ||--o{ encoder_encoderchatmessage : "job"
    encoder_encoderjob ||--o{ encoder_encoderexecution : "job"
    encoder_mcpconnection ||--o{ encoder_encoderexecution : "connection"
    router_documentroute ||--o| encoder_encoderjob : "route"
    encoder_mcpconnection o|--o{ encoder_encoderjob : "connection"
    encoder_mcpconnection ||--o{ encoder_encodermapping : "connection"
    encoder_encoderjob ||--o{ encoder_encoderreset : "job"
```
