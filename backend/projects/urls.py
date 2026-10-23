from django.urls import path

from projects import board_views, hub_views, invite_views, views

app_name = 'projects'

urlpatterns = [
    path('', views.project_list, name='list'),
    path('new/', views.project_new, name='new'),
    path('join/<str:token>/', invite_views.invitation_join, name='invitation_join'),
    path('<int:pk>/space/', hub_views.hub, name='hub'),
    path('<int:pk>/space/messages/', hub_views.message_add, name='message_add'),
    path(
        '<int:pk>/space/instructions/',
        hub_views.instructions_update,
        name='instructions_update',
    ),
    path('<int:pk>/', views.project_detail, name='detail'),
    path('<int:pk>/workspace/', views.project_link_workspace, name='link_workspace'),
    path('<int:pk>/open/', views.project_open, name='open'),
    path('<int:pk>/invitations/', invite_views.invitation_list, name='invitation_list'),
    path(
        '<int:pk>/invitations/new/',
        invite_views.invitation_create,
        name='invitation_create',
    ),
    path(
        '<int:pk>/invitations/<uuid:invite_pk>/revoke/',
        invite_views.invitation_revoke,
        name='invitation_revoke',
    ),
    path('<int:pk>/board/', board_views.board, name='board'),
    path('<int:pk>/board/members/', board_views.member_add, name='member_add'),
    path(
        '<int:pk>/board/members/<int:member_pk>/',
        board_views.member_update,
        name='member_update',
    ),
    path('<int:pk>/board/tasks/', board_views.task_add, name='task_add'),
    path('<int:pk>/board/tasks/<int:task_pk>/', board_views.task_update, name='task_update'),
    path('<int:pk>/board/workspace/', board_views.board_workspace, name='board_workspace'),
]
