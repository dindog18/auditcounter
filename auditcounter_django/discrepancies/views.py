from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from .services.dashboard import parse_filters,cases,summary

@require_GET
def dashboard(request):
    return render(request,'discrepancies/dashboard.html',{'section':'discrepancies','page_title':'Discrepancies'})


def response(request,operation):
    filters,errors=parse_filters(request.GET)
    if errors: return JsonResponse({'message':'Invalid dashboard filters.','errors':errors},status=400)
    return JsonResponse(operation(filters))

@require_GET
def case_list(request):
    return response(request,cases)

@require_GET
def case_summary(request):
    return response(request,summary)


@require_GET
def case_timeline(request,mode,case_id):
    from django.shortcuts import get_object_or_404
    from accounts_receivable.services.catalog import model
    from .services.timeline import timeline
    if mode not in ('ap','ar'):
        return JsonResponse({'message':'Choose ap or ar.'},status=400)
    if set(request.GET)-{'category','page','page_size'} or any(len(request.GET.getlist(key))!=1 for key in request.GET):
        return JsonResponse({'message':'Invalid timeline parameters.'},status=400)
    category=request.GET.get('category','')
    try:
        page=int(request.GET.get('page','1'));size=int(request.GET.get('page_size','25'))
        if page<1 or page>1000000 or size<1 or size>100 or category not in ('','documents','matching','discrepancies','payments','investigations'):raise ValueError()
    except ValueError:
        return JsonResponse({'message':'Invalid timeline filters or pagination.'},status=400)
    case=get_object_or_404(model(mode,'Transaction'),pk=case_id)
    return JsonResponse(timeline(case,category,page,size))
