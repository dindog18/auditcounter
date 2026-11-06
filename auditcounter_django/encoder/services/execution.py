"""Signed payload review, atomic attempt claims, explicit retries, no auto-execution."""
import hashlib
import json
import os
import uuid

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from mcp.client.stdio import get_default_environment

from document_extraction.models import Document
from router.models import DocumentRoute
from router.services.records import _current_attempt
from ..models import EncoderExecution, EncoderJob, MCPConnection
from . import discovery, mcp_client, validation


def retry_identity(job):
    connection = job.connection
    profile = settings.ENCODER_STDIO_SERVERS.get(connection.launch_profile, {})
    content = {"job": job.pk, "payload": job.prepared_payload,
               "schema": job.tool_schema, "tool": job.tool_name, "connection": connection.pk,
               "profile": profile, "timeout": connection.timeout_seconds,
               "command": connection.command, "arguments": connection.arguments, "cwd": connection.working_directory,
               "inline_environment": connection.environment,
               "passthrough": {name: os.environ.get(name, "") for name in connection.environment_passthrough},
               "transport": connection.transport, "url": connection.server_url, "http_headers": connection.http_headers,
               "bearer_env": connection.bearer_token_env_var, "bearer_value": os.environ.get(connection.bearer_token_env_var, ""),
               "header_env": connection.env_http_headers,
               "header_values": {str(name): os.environ.get(variable, "") for name, variable in connection.env_http_headers.items()},
               # Only the final digest leaves this function; never persist credential values.
               "environment": {name: os.environ.get(name, "") for name in profile.get("env", [])},
               "idempotency_field": job.idempotency_field}
    if connection.transport == "stdio":
        content["stdio_defaults"] = get_default_environment()
        content["server_cwd"] = os.getcwd()
    else:
        content["http_environment"] = {
            name: value for name, value in os.environ.items()
            if name.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy", "ssl_cert_file", "ssl_cert_dir"}
        }
    return salted_hmac("encoder-retry-identity", json.dumps(content, sort_keys=True), algorithm="sha256").hexdigest()


def identity(job):
    revisions = f"{job.updated_at.isoformat()}:{job.connection.updated_at.isoformat()}"
    return hashlib.sha256(f"{revisions}:{retry_identity(job)}".encode()).hexdigest()


def outstanding_attempts(job):
    return EncoderExecution.objects.filter(
        job__route__routing_log__source_document=job.document,
        status__in=["processing", "unknown"], reconciled_at__isnull=True,
    ).order_by("pk")


def review_token(job, unknown_attempts=None):
    if job.status != "ready" or not job.connection_id:
        return ""
    if unknown_attempts is None:
        unknown_attempts = outstanding_attempts(job).filter(status="unknown")
    return signing.dumps({
        "identity": identity(job), "request_id": str(uuid.uuid4()), "job": job.pk,
        "unknown_attempt_ids": [attempt.pk for attempt in unknown_attempts],
    }, salt="encoder-execute")


def route_approved(job):
    route = job.route
    _current_attempt(route.routing_log)
    if (route.review_status != "approved" or job.document.review_status != "approved"
            or not route.destination.is_active or route.destination.module_name != "encoder"
            or route.destination.target_model != "EncoderJob" or route.processing_status != "completed"):
        raise ValidationError("Approve the current source document and MCP Encoder route before executing.")


def execute(job_id, token, *, confirmed=False, reconciled=False):
    if confirmed is not True:
        raise ValidationError("Explicitly confirm the reviewed payload before executing an MCP tool.")
    try:
        reviewed = signing.loads(token, salt="encoder-execute", max_age=1800)
    except (signing.BadSignature, TypeError):
        raise ValidationError("Review and validate the payload again; execution confirmation expired or is invalid.") from None
    with transaction.atomic():
        initial = EncoderJob.objects.get(pk=job_id)
        # Same lock order as Router/extraction prevents a simultaneous reroute.
        Document.objects.select_for_update().get(pk=initial.document.pk)
        DocumentRoute.objects.select_for_update().get(pk=initial.route_id)
        job = EncoderJob.objects.select_for_update(of=("self",)).select_related("connection", "route__routing_log__source_document", "route__destination").get(pk=job_id)
        if reviewed.get("job") != job.pk:
            raise ValidationError("This confirmation belongs to another job.")
        previous = EncoderExecution.objects.filter(request_id=reviewed["request_id"]).first()
        if previous:
            return previous  # A browser replay never causes another external call.
        MCPConnection.objects.select_for_update().get(pk=job.connection_id)
        job.connection.refresh_from_db()
        if job.status != "ready" or reviewed.get("identity") != identity(job):
            raise ValidationError("The payload or connection changed. Review and validate again.")
        route_approved(job)
        discovery.tool(job.connection, job.tool_name)
        issues = validation.errors(job.prepared_payload, job.tool_schema)
        if issues:
            raise ValidationError("Resolve payload validation issues before executing.")
        outstanding = list(outstanding_attempts(job))
        if any(previous.status == "processing" for previous in outstanding):
            raise ValidationError("Wait for the previous external operation on this document to finish.")
        fingerprint = retry_identity(job)
        if outstanding:
            if reconciled:
                attempt_ids = [previous.pk for previous in outstanding]
                if reviewed.get("unknown_attempt_ids") != attempt_ids:
                    raise ValidationError("The execution history changed. Reload and review the uncertain outcomes.")
                EncoderExecution.objects.filter(pk__in=attempt_ids).update(reconciled_at=timezone.now())
            elif not job.idempotency_field or any(
                previous.job_id != job.pk or previous.connection_snapshot.get("retry_identity") != fingerprint
                for previous in outstanding
            ):
                raise ValidationError("The previous external outcome is unknown. Verify externally that it did not succeed, then confirm reconciliation before retrying.")
        attempt = EncoderExecution.objects.create(request_id=reviewed["request_id"], job=job, cycle=job.cycle,
            connection=job.connection, tool_name=job.tool_name, tool_schema=job.tool_schema,
            payload=job.prepared_payload, connection_snapshot={"name": job.connection.name,
                "launch_profile": job.connection.launch_profile, "revision": job.connection.updated_at.isoformat(),
                "retry_identity": fingerprint})
        job.status = "processing"
        job.save(update_fields=["status", "updated_at"])
    # Release database locks before bounded subprocess I/O. The job is now claimed.
    invoked = False
    try:
        client = mcp_client.connector(job.connection)
        live = next((row for row in client.discover() if row["name"] == job.tool_name), None)
        if live is None or live.get("inputSchema") != job.tool_schema:
            raise ValidationError("The live tool schema changed. Rediscover tools and select the operation again.")
        invoked = True
        attempt.response = client.call(job.tool_name, job.prepared_payload, job.tool_schema)
        if attempt.response.get("isError"):
            attempt.status = "unknown"
            attempt.error_message = "The MCP tool reported an error. Review the response and verify whether any external change occurred."
        else:
            attempt.status = "completed"
    except Exception as error:
        attempt.status = "unknown" if invoked else "failed"
        attempt.error_message = "; ".join(error.messages) if isinstance(error, ValidationError) else "MCP execution failed. Check the server configuration and availability."
    attempt.finished_at = timezone.now()
    with transaction.atomic():
        attempt.save()
        EncoderJob.objects.filter(pk=job.pk, status="processing").update(
            status="completed" if attempt.status == "completed" else "failed", last_error=attempt.error_message,
            updated_at=timezone.now())
    return attempt
