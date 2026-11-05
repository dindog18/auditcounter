# auth ER diagram

Tables owned by `auth` include all local fields. Referenced tables from other apps show only their primary key; see the [diagram index](../auditcounter-django-erd.md) for their full definitions. Relationships are shown in the diagram of the app that owns the foreign key.

```mermaid
erDiagram
    auth_group {
        AutoField id PK
        CharField name UK
    }
    auth_group_permissions {
        AutoField id PK
        ForeignKey group_id FK
        ForeignKey permission_id FK
    }
    auth_permission {
        AutoField id PK
        CharField name
        ForeignKey content_type_id FK
        CharField codename
    }
    auth_user {
        AutoField id PK
        CharField password
        DateTimeField last_login
        BooleanField is_superuser
        CharField username UK
        CharField first_name
        CharField last_name
        CharField email
        BooleanField is_staff
        BooleanField is_active
        DateTimeField date_joined
    }
    auth_user_groups {
        AutoField id PK
        ForeignKey user_id FK
        ForeignKey group_id FK
    }
    auth_user_user_permissions {
        AutoField id PK
        ForeignKey user_id FK
        ForeignKey permission_id FK
    }
    django_content_type {
        AutoField id PK
    }
    auth_group ||--o{ auth_group_permissions : "group"
    auth_permission ||--o{ auth_group_permissions : "permission"
    django_content_type ||--o{ auth_permission : "content_type"
    auth_user ||--o{ auth_user_groups : "user"
    auth_group ||--o{ auth_user_groups : "group"
    auth_user ||--o{ auth_user_user_permissions : "user"
    auth_permission ||--o{ auth_user_user_permissions : "permission"
```
