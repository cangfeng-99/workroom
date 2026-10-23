from django.urls import path

from projects import views

app_name = 'projects'

urlpatterns = [
    path('', views.project_list, name='list'),
    path('new/', views.project_new, name='new'),
    path('<int:pk>/', views.project_detail, name='detail'),
    path('<int:pk>/workspace/', views.project_link_workspace, name='link_workspace'),
    path('<int:pk>/open/', views.project_open, name='open'),
]
