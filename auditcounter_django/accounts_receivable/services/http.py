"""Shared JSON actions for the two accounting workspaces."""

import json

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from . import assistant, configuration, configuration_chat, pages, records
from .catalog import model


def perform(request, mode, action, record_id=None):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValidationError("Expected a JSON object.")
        if action=='root-cause-review' and record_id:
            from discrepancies.services.analytics import review_root_cause,serialize_root_cause
            case=get_object_or_404(model(mode,'Transaction'),pk=record_id)
            return JsonResponse({'root_cause':serialize_root_cause(review_root_cause(case,data))})
        if mode=='ar' and action in {'deduction-create','deduction-review','deduction-apply','deduction-reverse'}:
            from . import deductions
            result=deductions.create_deduction(data) if action=='deduction-create' else {'deduction-review':deductions.review,'deduction-apply':deductions.apply,'deduction-reverse':deductions.reverse_application}[action](record_id,data)
            return JsonResponse({'id':result.pk})
        if mode=='ap' and action in {'statement-create','statement-reconcile','statement-review'}:
            from accounts_payable.services import statements
            result=statements.create_statement(data) if action=='statement-create' else statements.reconcile(record_id,data) if action=='statement-reconcile' else statements.review_line(record_id,data)
            return JsonResponse({'id':result.pk})
        if mode=='ap' and action in {'claim-create','claim-transition','claim-correspondence','claim-resolve'} and record_id:
            from discrepancies.services import claims
            operation={'claim-create':claims.create_claim,'claim-transition':claims.transition,'claim-correspondence':claims.correspond,'claim-resolve':claims.resolve}[action]
            return JsonResponse({'claim':claims.serialize(operation(record_id,data))})
        if action=='duplicate-scan' and record_id:
            from discrepancies.services.duplicate_invoices import detect
            from .catalog import check_revision,party_key
            from .financial import body
            body(data,('revision',))
            with transaction.atomic():
                invoice=get_object_or_404(model(mode,'sales_invoice'),pk=record_id)
                model(mode,party_key(mode)).objects.select_for_update().get(pk=getattr(invoice,party_key(mode)+'_id'))
                invoice=model(mode,'sales_invoice').objects.get(pk=record_id)
                check_revision(invoice,data.get('revision'))
                candidates=detect(invoice)
                invoice_ids={invoice.pk}
                for candidate in candidates:
                    invoice_ids.update((getattr(candidate,mode+'_first_id'),getattr(candidate,mode+'_second_id')))
                for case in model(mode,'Transaction').objects.filter(sales_invoices__pk__in=invoice_ids).distinct().order_by('pk'):
                    case.refresh_reconciliation_status()
            return JsonResponse({'candidate_ids':[row.pk for row in candidates]})
        if mode=='ap' and action in {'credit-create','credit-verify','credit-apply','credit-reverse'}:
            from accounts_payable.services import credits
            if action=='credit-create':
                result=credits.create_credit(data)
            elif action=='credit-verify':
                result=credits.verify_credit(record_id,data)
            elif action=='credit-apply':
                result=credits.apply_credit(record_id,data)
            else:
                result=credits.reverse_application(record_id,data)
            return JsonResponse({'id':result.pk})
        if action == 'record-delete' and record_id:
            records.delete_document(mode, data.get('resource'), record_id, data)
            return JsonResponse({'deleted': True, 'id': record_id})
        if action == 'configuration-delete' and record_id:
            configuration.delete(mode, record_id, data)
            return JsonResponse({'deleted':True, 'id':record_id})
        if action.startswith("setup-"):
            from .setup.actions import perform as setup_action
            return JsonResponse(setup_action(request, mode, action, data, record_id))
        if action in {"configuration-review", "configuration", "submit"}:
            values = data.get("configuration", {})
            setup = values.get("setup_data", {}) if isinstance(values, dict) else {}
            saved = model(mode, "ExtractionConfiguration").objects.filter(pk=record_id).first() if record_id else None
            saved_setup = saved.setup_data if saved else {}
            if (isinstance(setup, dict) and setup.get("version") == 1) or (isinstance(saved_setup, dict) and saved_setup.get("version") == 1):
                from .setup.actions import perform as setup_action
                if action != "configuration-review":
                    data["submit"] = action == "submit"
                return JsonResponse(setup_action(request, mode, "setup-review" if action == "configuration-review" else "setup-save", data, record_id))
        if action in {"parties", "reconciliation"}:
            record = records.save_party(mode, data, record_id) if action == "parties" else records.save_case(mode, data, record_id)
            return JsonResponse({"id": record.pk})
        if action in {'sku-suggest','sku-approve','sku-reject','sku-deactivate','sku-mappings'} and record_id:
            from sku_matching.services import mapping, suggestions
            from sku_matching.services.presentation import workspace_state as sku_state
            case=get_object_or_404(model(mode,'Transaction'),pk=record_id)
            if action=='sku-suggest':
                suggestions.suggest_sku_equivalence(case,data)
            elif action!='sku-mappings':
                operations={'sku-approve':mapping.approve_mapping,'sku-reject':mapping.reject_mapping,'sku-deactivate':mapping.deactivate_mapping}
                operations[action](case,data)
            else:
                mapping.validate_body(data,())
            response={'sku':sku_state(case)}
            if action in {'sku-approve','sku-deactivate'}:
                from .catalog import revision
                case.refresh_from_db()
                response['matchRevision']=revision(case,[records.case_membership(case),records.matches(case)])
            return JsonResponse(response)
        if action in {'investigation-start','investigation-update','investigation-note','finding-review','investigation-resolve','investigation-reopen'} and record_id:
            from discrepancies.services import investigation
            operations={'investigation-start':investigation.start_investigation,'investigation-update':investigation.update_investigation,
                'investigation-note':investigation.add_investigation_note,'finding-review':investigation.review_finding,
                'investigation-resolve':investigation.resolve_investigation,'investigation-reopen':investigation.reopen_investigation}
            case=get_object_or_404(model(mode,'Transaction'),pk=record_id)
            result=operations[action](case,data)
            return JsonResponse({'id':result.pk,'case_id':case.pk})
        if action == "recalculate" and record_id:
            from .catalog import check_revision, party_key
            with transaction.atomic():
                case = get_object_or_404(model(mode,"Transaction"), pk=record_id)
                if getattr(case,party_key(mode)+'_id'):
                    model(mode,party_key(mode)).objects.select_for_update().get(pk=getattr(case,party_key(mode)+'_id'))
                case = model(mode,"Transaction").objects.select_for_update().get(pk=record_id)
                check_revision(case, data.get('revision'), [records.case_membership(case),records.matches(case)])
                from discrepancies.services.duplicate_invoices import detect
                for invoice in case.sales_invoices.order_by('pk'):
                    detect(invoice)
                case.refresh_reconciliation_status()
            return JsonResponse({'id':case.pk})
        if action == "match-suggestions" and record_id:
            from .auto_matching import generate_match_suggestions
            from .catalog import check_revision
            case = get_object_or_404(model(mode, "Transaction"), pk=record_id)
            check_revision(case, data.get('revision'), [records.case_membership(case), records.matches(case)])
            return JsonResponse(generate_match_suggestions(case, current_rows=data.get('matches')))
        if action == "matches-preview" and record_id:
            return JsonResponse(records.preview_matches(mode, record_id, data))
        if action in {"allocations", "matches"} and record_id:
            record = records.save_allocations(mode, record_id, data) if action == "allocations" else records.save_matches(mode, record_id, data)
            return JsonResponse({"id": record.pk})
        if action == "configuration-context":
            return JsonResponse(configuration_chat.setup_context(mode, data, record_id))
        if action == "configuration-reset-context":
            return JsonResponse(configuration_chat.reset_context(mode, data, record_id))
        if action == "configuration-chat":
            return JsonResponse(configuration_chat.chat(mode, data, record_id))
        if action == "configuration-preview":
            return JsonResponse(configuration_chat.preview(mode, data, record_id))
        if action == "configuration-review":
            return JsonResponse(configuration_chat.review(mode, data, record_id, request.user))
        if action in {"configuration", "submit"}:
            data["submit"] = action == "submit"
            values = data.get('configuration', {})
            saved = model(mode, 'ExtractionConfiguration').objects.filter(pk=record_id).first() if record_id else None
            if values.get('source_type') == 'database' or saved and saved.source_type == 'database':
                raise ValidationError('Open the database setup and review the full migration before saving.')
            with transaction.atomic():
                record = configuration_chat.confirm(mode, data, record_id, request.user)
            return JsonResponse({"record": pages.configuration(record, mode)})
        if action == "assistant" and record_id:
            record = assistant.propose(mode, record_id, data)
            return JsonResponse({"record": pages.configuration(record, mode), "llm_log_no": record.assistant_proposal["llm_log_no"]})
        if action == "import" and record_id:
            raise ValidationError('Open the saved extraction setup and use Update data. The full result must pass review before any rows are updated.')
        if action == "accuracy" and record_id:
            with transaction.atomic():
                log = get_object_or_404(model(mode, "LLMExtractionLog").objects.select_for_update(), pk=record_id)
                if data.get("revision") != log.updated_at.isoformat():
                    raise ValidationError("The attempt changed. Reload before reviewing.", code="conflict")
                if log.status != "completed" or type(data.get("accurate")) is not bool:
                    raise ValidationError("Only a completed attempt can be marked accurate.")
                log.user_selected_accurate = data["accurate"]
                log.reviewed_at = timezone.now()
                log.reviewed_by = request.user if request.user.is_authenticated else None
                log.save(update_fields=["user_selected_accurate", "reviewed_at", "reviewed_by", "updated_at"])
            return JsonResponse({"record": pages.llm_log(log)})
        raise ValidationError("Unsupported accounting action.")
    except (ValidationError, ValueError, TypeError, KeyError, OverflowError) as error:
        message = "; ".join(error.messages) if isinstance(error, ValidationError) else "Invalid request. Check the submitted fields and reload if necessary."
        result = {"message": message}
        if getattr(error,"existing_case",None):
            result.update(error.existing_case)
        if getattr(error, "llm_log_no", None):
            result["llm_log_no"] = error.llm_log_no
        return JsonResponse(result, status=409 if getattr(error, "code", None) == "conflict" else 400)
    except IntegrityError:
        return JsonResponse({"message": "A conflicting record already exists. Reload and check its reference or source."}, status=409)
    except DatabaseError:
        return JsonResponse({'message':'The accounting database could not complete this operation. No partial migration or update was committed. Reload and review again.'}, status=503)
