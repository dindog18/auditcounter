# db_extraction ER diagram

Tables owned by `db_extraction` include all local fields. Referenced tables from other apps show only their primary key; see the [diagram index](../auditcounter-django-erd.md) for their full definitions. Relationships are shown in the diagram of the app that owns the foreign key.

```mermaid
erDiagram
    db_extraction_constraintcolumn {
        BigAutoField id PK
        ForeignKey constraint_id FK
        ForeignKey column_id FK
        PositiveIntegerField position
        CharField referenced_column_name
    }
    db_extraction_databasecolumn {
        BigAutoField id PK
        ForeignKey table_id FK
        CharField name
        PositiveIntegerField ordinal_position
        TextField formatted_type
        CharField type_schema
        CharField type_name
        CharField domain_schema
        CharField domain_name
        BooleanField nullable
        TextField default_expression
        PositiveIntegerField character_maximum_length
        PositiveIntegerField numeric_precision
        IntegerField numeric_scale
        CharField identity_generation
        TextField generated_expression
        CharField collation_schema
        CharField collation_name
        TextField comment
    }
    db_extraction_databaseconstraint {
        BigAutoField id PK
        ForeignKey table_id FK
        CharField name
        CharField constraint_type
        TextField definition
        CharField referenced_schema
        CharField referenced_table
        CharField update_action
        CharField delete_action
        CharField match_type
        BooleanField is_deferrable
        BooleanField initially_deferred
        BooleanField is_validated
    }
    db_extraction_databaseindex {
        BigAutoField id PK
        ForeignKey table_id FK
        CharField name
        TextField definition
        CharField access_method
        BooleanField is_unique
        BooleanField is_primary
        BooleanField is_valid
        TextField predicate
        TextField comment
    }
    db_extraction_databaseschema {
        BigAutoField id PK
        ForeignKey run_id FK
        CharField name
        CharField owner
        TextField comment
    }
    db_extraction_databasesource {
        BigAutoField id PK
        CharField name UK
        CharField host
        PositiveIntegerField port
        CharField database_name
        CharField username
        TextField password
        CharField ssl_mode
        CharField ssl_root_cert
        PositiveIntegerField connect_timeout
        BooleanField enabled
        JSONField included_schemas
        DateTimeField created_at
        DateTimeField updated_at
    }
    db_extraction_databasetable {
        BigAutoField id PK
        ForeignKey schema_id FK
        CharField name
        CharField relation_kind
        CharField owner
        TextField comment
        TextField view_definition
        TextField partition_definition
        BooleanField row_security_enabled
    }
    db_extraction_extractionrun {
        BigAutoField id PK
        ForeignKey source_id FK
        CharField status
        DateTimeField created_at
        DateTimeField started_at
        DateTimeField finished_at
        CharField database_name
        CharField server_version
        CharField extractor_version
        JSONField included_schemas
        TextField error_message
    }
    db_extraction_databaseconstraint ||--o{ db_extraction_constraintcolumn : "constraint"
    db_extraction_databasecolumn ||--o{ db_extraction_constraintcolumn : "column"
    db_extraction_databasetable ||--o{ db_extraction_databasecolumn : "table"
    db_extraction_databasetable ||--o{ db_extraction_databaseconstraint : "table"
    db_extraction_databasetable ||--o{ db_extraction_databaseindex : "table"
    db_extraction_extractionrun ||--o{ db_extraction_databaseschema : "run"
    db_extraction_databaseschema ||--o{ db_extraction_databasetable : "schema"
    db_extraction_databasesource ||--o{ db_extraction_extractionrun : "source"
```
