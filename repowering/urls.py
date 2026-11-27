from django.contrib import admin
from django.urls import path
from windenergy import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.index, name="dashboard"),
    path("map/", views.turbine_map, name="turbine-map"),
    path("chat/", views.chat, name="chat"),
    path("fragen/", views.questions_page, name="questions"),
    path("fragen/csv/", views.questions_csv, name="questions-csv"),
    path("abfrage-vorschlagen/", views.suggest_query, name="query-suggestion"),
]
