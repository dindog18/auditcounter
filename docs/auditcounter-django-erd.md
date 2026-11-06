# Auditcounter Django entity relationship diagrams

These diagrams are generated from the current Django model definitions and installed apps. They cover all project and Django built-in models, including automatically generated many-to-many tables. Select an app to open its diagram. Cross-app references are included in the diagram owning the foreign key; referenced tables appear there with their primary key only.

| Django app | Diagram | Tables |
| --- | --- | ---: |
| `accounts_payable` | [accounts_payable](auditcounter-erd/accounts_payable.md) | 24 |
| `accounts_receivable` | [accounts_receivable](auditcounter-erd/accounts_receivable.md) | 21 |
| `admin` | [admin](auditcounter-erd/admin.md) | 1 |
| `auth` | [auth](auditcounter-erd/auth.md) | 6 |
| `contenttypes` | [contenttypes](auditcounter-erd/contenttypes.md) | 1 |
| `db_extraction` | [db_extraction](auditcounter-erd/db_extraction.md) | 8 |
| `discrepancies` | [discrepancies](auditcounter-erd/discrepancies.md) | 13 |
| `document_extraction` | [document_extraction](auditcounter-erd/document_extraction.md) | 5 |
| `encoder` | [encoder](auditcounter-erd/encoder.md) | 6 |
| `router` | [router](auditcounter-erd/router.md) | 4 |
| `sessions` | [sessions](auditcounter-erd/sessions.md) | 1 |
| `sku_matching` | [sku_matching](auditcounter-erd/sku_matching.md) | 2 |

Total: 92 tables, including 12 automatically generated many-to-many tables.

Entity names are database table names; field types are Django field types. `PK`, `FK`, and `UK` denote primary, foreign, and individually unique fields. Cardinality: `||` exactly one, `o|` zero or one, `o{` zero or more. A nullable foreign key permits zero or one parent; a unique or one-to-one foreign key permits at most one child.

Composite constraints, indexes, defaults, delete behavior, field nullability, and generic relations are not depicted. The diagrams reflect model definitions, which may differ from a database if migrations have not been applied.
