from django.contrib.auth.views import LogoutView
from django.urls import path
from django.views.decorators.cache import never_cache

from accounts import views

app_name = 'accounts'

urlpatterns = [
    path('signup/', never_cache(views.SignupView.as_view()), name='signup'),
    path('login/', never_cache(views.AccountLoginView.as_view()), name='login'),
    path('logout/', LogoutView.as_view(next_page='core:home'), name='logout'),
]
