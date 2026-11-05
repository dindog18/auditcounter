# admin ER diagram

Tables owned by `admin` include all local fields. Referenced tables from other apps show only their primary key; see the [diagram index](../auditcounter-django-erd.md) for their full definitions. Relationships are shown in the diagram of the app that owns the foreign key.

```mermaid
erDiagram
    auth_user {
        AutoField id PK
    }
    django_admin_log {
        AutoField id PK
        DateTimeField action_time
        ForeignKey user_id FK
        ForeignKey content_type_id FK
        TextField object_id
        CharField object_repr
        PositiveSmallIntegerField action_flag
        TextField change_message
    }
    django_content_type {
        AutoField id PK
    }
    auth_user ||--o{ django_admin_log : "user"
    django_content_type o|--o{ django_admin_log : "content_type"
```
