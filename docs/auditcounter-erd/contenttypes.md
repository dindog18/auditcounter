# contenttypes ER diagram

Tables owned by `contenttypes` include all local fields. Referenced tables from other apps show only their primary key; see the [diagram index](../auditcounter-django-erd.md) for their full definitions. Relationships are shown in the diagram of the app that owns the foreign key.

```mermaid
erDiagram
    django_content_type {
        AutoField id PK
        CharField app_label
        CharField model
    }
```
