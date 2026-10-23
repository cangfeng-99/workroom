from django.urls import path

from workspaces import views

app_name = 'workspaces'

urlpatterns = [
    path('', views.workspace_page, name='workspace'),
]
