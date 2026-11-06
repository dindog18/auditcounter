# Document extraction

The Documents workspace (`/documents/`) owns uploaded originals, batches, extracted Markdown and human review. Start here when accounting input comes from files.

## Flow

1. **Upload documents** validates the submitted files, creates a batch and stores originals. Supported text-based files use local parsers. Images use the configured extraction provider; scanned PDFs require a suitable OCR workflow.
2. The app records each text or provider attempt separately. Open a document to compare the original with an extraction, edit its Markdown if needed and record the review. Processing status, document review and each attempt’s accuracy flag are separate.
3. **Re-Run** uses the saved originals and current settings, preserves prior attempts and resets review to pending. Edits and reruns reject conflicting operations.
4. **Route document**, **Route selected** and **Route batch** hand off saved text to the [Router](../router/README.md). Routing prefers a usable attempt marked accurate, otherwise the most recent usable attempt.

## Structure

- [urls.py](urls.py) and [views.py](views.py) — document, batch, preview and extraction endpoints.
- [models.py](models.py) — batches, documents, extraction attempts and workspace setup preferences.
- [services/uploads.py](services/uploads.py), [services/storage.py](services/storage.py), [services/documents.py](services/documents.py) and [services/images.py](services/images.py) — intake, storage and parsing.
- [services/records.py](services/records.py) and [services/management.py](services/management.py) — review, edits and record management.
- [services/llm.py](services/llm.py) — provider transport shared with other workspaces.
- [FRONTEND.md](FRONTEND.md) — workspace screens, file previews, editing and route details.

## Workspace help

[help_views.py](help_views.py) receives the optional Help chat request. [services/help_assistant.py](services/help_assistant.py) supplies page guidance and shipped workflow summaries to the configured setup assistant model, then validates the reply and resolves known source IDs to workspace links. The chat receives no saved documents or accounting records. See [activation and provider settings](../../README.md#ask-auditcounter).
