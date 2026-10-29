from django.urls import include, path, re_path
from django.views.generic import RedirectView

urlpatterns = [
    path(
        'accounts/login/',
        RedirectView.as_view(url='/login/', permanent=False),
        name='legacy-login',
    ),
    # 旧工程留下的书签（/projects/、/accounts/ 等）一律回到新首页，
    # 用 302 而不是 301，避免浏览器把跳转永久缓存。
    re_path(r'^projects(?:/.*)?$', RedirectView.as_view(url='/', permanent=False)),
    re_path(r'^accounts(?:/.*)?$', RedirectView.as_view(url='/', permanent=False)),
    path('', include('apps.projects.urls')),
]
