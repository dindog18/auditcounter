from django.urls import path
from . import views
app_name='DISCREPANCIES'
urlpatterns=[path("api/cases/<str:mode>/<int:case_id>/timeline/",views.case_timeline,name="timeline"),path('',views.dashboard,name='dashboard'),path('api/cases/',views.case_list,name='cases'),path('api/summary/',views.case_summary,name='summary')]
urlpatterns += [path('api/duplicate-invoices/',views.duplicate_candidates,name='duplicate_candidates'),path('api/duplicate-invoices/<int:record_id>/review/',views.duplicate_review,name='duplicate_review')]

urlpatterns += [path('api/analytics/',views.analytics,name='analytics')]
