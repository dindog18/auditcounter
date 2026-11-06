# Django project

This package wires together the AuditCounter workspaces. Start Django through [manage.py](../manage.py) after following the [root setup guide](../../README.md).

## Flow

1. `settings.py` registers the apps, middleware, templates, application database and static assets. `environment.py` loads the project’s `.env` with process variables taking precedence.
2. `urls.py` mounts Documents, Router, Database connections, AP, AR and the optional MCP Encoder. The accounting document apps use the AP/AR routes.
3. **Guided Setup** walks through the selected record and workflow setup paths. **Settings & setup** checks saved readiness and stores workspace preferences for which modules show reminders. Those preferences control visibility of reminders.
4. Shared templates receive page guidance from `onboarding.py` and `page_help.py`. The Help button starts the page tour or, when enabled, offers [Ask AuditCounter](../document_extraction/README.md#workspace-help).

## Structure

- [settings.py](settings.py), [environment.py](environment.py), [urls.py](urls.py) — configuration and routing.
- [onboarding.py](onboarding.py), [page_help.py](page_help.py) — setup checks, setup endpoints and route-specific tours.
- [wsgi.py](wsgi.py), [asgi.py](asgi.py) — deployment entry points.

See the [module index](../../README.md#module-guide) for ownership and workspace entry points.
