"""HTTP entry point for the workspace help assistant."""

import logging
from time import time

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from pydantic import ValidationError

from auditcounter_django.page_help import GUIDES
from .services.help_assistant import HelpRequest, WORKSPACES, answer_question

logger = logging.getLogger(__name__)


@never_cache
@require_POST
@csrf_protect
def ask_help(request):
    if not settings.HELP_ASSISTANT_ENABLED:
        return JsonResponse({"error": "Ask AuditCounter is disabled."}, status=404)
    if request.content_type != "application/json":
        return JsonResponse({"error": "Send a JSON request."}, status=415)
    try:
        body = request.body
    except RequestDataTooBig:
        body = None
    if body is None or len(body) > 48 * 1024:
        return JsonResponse({"error": "This request is too long. Start a new conversation."}, status=413)
    try:
        query = HelpRequest.model_validate_json(body)
    except ValidationError:
        return JsonResponse({"error": "Enter a question of up to 1,000 characters."}, status=400)
    if query.page not in GUIDES or query.workspace not in WORKSPACES or len(query.history) > 3:
        return JsonResponse({"error": "Refresh this page and try again."}, status=400)

    # Do not trust client-provided forwarded headers. Behind a reverse proxy
    # this deliberately shares the allowance across that proxy's requests.
    key = f"workspace-help:{request.META.get('REMOTE_ADDR', 'unknown')}:{int(time()) // 60}"
    cache.add(key, 0, timeout=65)
    if cache.incr(key) > 10:
        return JsonResponse({"error": "Too many help requests. Wait a minute and try again."}, status=429)
    try:
        return JsonResponse(answer_question(query))
    except Exception as error:
        logger.warning("Workspace help request failed (%s).", type(error).__name__)
        return JsonResponse({"error": "The assistant is unavailable right now. Try again or use the guided tour."}, status=503)
