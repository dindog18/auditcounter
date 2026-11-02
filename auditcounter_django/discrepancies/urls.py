from django.urls import path
from . import views
app_name='DISCREPANCIES'
urlpatterns=[path("api/cases/<str:mode>/<int:case_id>/timeline/",views.case_timeline,name="timeline"),path('',views.dashboard,name='dashboard'),path('api/cases/',views.case_list,name='cases'),path('api/summary/',views.case_summary,name='summary')]
