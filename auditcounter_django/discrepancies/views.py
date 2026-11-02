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
