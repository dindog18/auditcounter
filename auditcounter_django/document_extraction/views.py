"""HTTP handlers for the document workspace."""

import logging

from django.apps import apps
from django.http import FileResponse, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from .models import DocExtractionLog, Document, LLMExtractionLog
from .services import management, pages
from .services.originals import original_file_response
from .forms import DocumentUploadForm
from .services.documents import PDFExtractionError
from .services.uploads import process_document_upload

logger = logging.getLogger(__name__)


@never_cache
@require_safe
def home(request: HttpRequest) -> HttpResponse:
    """Use persisted workspace activity and a browser's completed setup as landing hints."""
    documents = "DOC_EXTRACTION:document_list"
    if request.COOKIES.get("auditcounter_guided_setup_finished") == "1" or Document.objects.exists():
        return redirect(documents)

    for app_label, party in (("accounts_payable", "Supplier"), ("accounts_receivable", "Customer")):
        if apps.get_model(app_label, party).objects.exists():
            return redirect(documents)
        if apps.get_model(app_label, "ExtractionConfiguration").objects.filter(
            status="submitted",
        ).exclude(submitted_snapshot={}).exists():
            return redirect(documents)

    if apps.get_model("router", "RoutingRule").objects.filter(
        is_active=True, destination__is_active=True, destination__is_deleted=False,
    ).exists():
        return redirect(documents)
    if apps.get_model("db_extraction", "ExtractionRun").objects.filter(source__enabled=True, status="completed").exists():
        return redirect(documents)
    if apps.get_model("encoder", "MCPConnection").objects.filter(
        enabled=True, discovered_at__isnull=False, discovery_error="",
    ).exists():
        return redirect(documents)
    return redirect("guided_setup")


@require_safe
def document_list(request: HttpRequest) -> HttpResponse:
    return render(request, "document_extraction/document_list.html", pages.document_list_context(request.GET))


@require_http_methods(["GET", "HEAD", "POST"])
def document_upload(request: HttpRequest) -> HttpResponse:
    submitted = request.method == "POST"
    form = DocumentUploadForm(request.POST if submitted else None, request.FILES if submitted else None)
    if submitted:
        logger.info("document_upload POST received")
        if not form.is_valid():
            logger.warning("document_upload validation failed fields=%s", ",".join(form.errors))
            return JsonResponse({"errors": form.errors.get_json_data()}, status=400)
        try:
            batch = process_document_upload(form.cleaned_data["files"])
        except PDFExtractionError as error:
            return JsonResponse({"errors": {"files": [{"message": str(error)}]}}, status=400)
        logger.info("batch=%s document_upload redirecting to batch detail", batch.batch_no)
        return redirect("DOC_EXTRACTION:batch_detail", batch_no=batch.batch_no)
    return render(request, "document_extraction/document_upload.html", {
        "page_title": "Upload documents and images", "section": "upload", "form": form,
    })


@require_safe
def document_detail(request: HttpRequest, document_no: int) -> HttpResponse:
    return render(request, "document_extraction/document_detail.html", pages.document_detail_context(document_no))


@require_safe
def document_original(request: HttpRequest, document_no: int) -> FileResponse:
    return original_file_response(document_no, download=request.GET.get("download") == "1")


@require_POST
def document_rerun(request: HttpRequest, document_no: int) -> HttpResponse:
    return management.rerun_response(request, document_no=document_no)


@require_POST
def batch_rerun(request: HttpRequest, batch_no: int) -> HttpResponse:
    return management.rerun_response(request, batch_no=batch_no)


@require_safe
def doc_extraction_detail(request: HttpRequest, document_no: int, doc_log_no: int) -> HttpResponse:
    return render(request, "document_extraction/extraction_detail.html", pages.extraction_detail_context(document_no, doc_log_no, DocExtractionLog))


@require_safe
def llm_extraction_detail(request: HttpRequest, document_no: int, llm_log_no: int) -> HttpResponse:
    return render(request, "document_extraction/extraction_detail.html", pages.extraction_detail_context(document_no, llm_log_no, LLMExtractionLog))


@require_http_methods(["GET", "HEAD", "POST"])
def llm_extraction_edit(request: HttpRequest, document_no: int, llm_log_no: int) -> HttpResponse:
    return management.extraction_edit_response(request, document_no, llm_log_no, LLMExtractionLog)


@require_http_methods(["GET", "HEAD", "POST"])
def doc_extraction_edit(request: HttpRequest, document_no: int, doc_log_no: int) -> HttpResponse:
    return management.extraction_edit_response(request, document_no, doc_log_no, DocExtractionLog)


@require_http_methods(["GET", "HEAD", "POST"])
def document_edit(request: HttpRequest, document_no: int) -> HttpResponse:
    return management.document_edit_response(request, document_no)


@require_http_methods(["GET", "HEAD", "POST"])
def doc_extraction_create(request: HttpRequest, document_no: int) -> HttpResponse:
    return management.extraction_create_response(request, document_no)


@require_POST
def document_review(request: HttpRequest, document_no: int) -> HttpResponse:
    return management.review_response(request, document_no)


@require_POST
def doc_extraction_accuracy(request: HttpRequest, document_no: int, doc_log_no: int) -> HttpResponse:
    return management.accuracy_response(request, document_no, doc_log_no, DocExtractionLog)


@require_POST
def llm_extraction_accuracy(request: HttpRequest, document_no: int, llm_log_no: int) -> HttpResponse:
    return management.accuracy_response(request, document_no, llm_log_no, LLMExtractionLog)


@require_http_methods(["GET", "HEAD", "POST"])
def document_delete(request: HttpRequest, document_no: int) -> HttpResponse:
    return management.delete_response(request, document_no)


@require_http_methods(["GET", "HEAD", "POST"])
def doc_extraction_delete(request: HttpRequest, document_no: int, doc_log_no: int) -> HttpResponse:
    return management.delete_response(request, document_no, DocExtractionLog, doc_log_no)


@require_http_methods(["GET", "HEAD", "POST"])
def llm_extraction_delete(request: HttpRequest, document_no: int, llm_log_no: int) -> HttpResponse:
    return management.delete_response(request, document_no, LLMExtractionLog, llm_log_no)


@require_safe
def batch_list(request: HttpRequest) -> HttpResponse:
    return render(request, "document_extraction/batch_list.html", pages.batch_list_context(request.GET))


@require_safe
def batch_detail(request: HttpRequest, batch_no: int) -> HttpResponse:
    return render(request, "document_extraction/batch_detail.html", pages.batch_detail_context(request.GET, batch_no))
