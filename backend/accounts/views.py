"""Signup, login and logout using Django's built-in auth views."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic.edit import FormView
from workspaces.grants import clear_grant

from accounts.forms import SignupForm


class SignupView(FormView):
    template_name = 'accounts/signup.html'
    form_class = SignupForm

    def safe_next(self) -> str:
        """Only an internal destination already allowed by Django is kept."""
        raw = self.request.POST.get('next') or self.request.GET.get('next') or ''
        if raw and url_has_allowed_host_and_scheme(
            raw,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return raw
        return ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['next'] = self.safe_next()
        return context

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        # A new identity must not inherit a folder grant from the session.
        clear_grant(self.request)
        return redirect(self.safe_next() or settings.LOGIN_REDIRECT_URL)


class AccountLoginView(LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        # Never carry a pre-login folder grant into the authenticated session.
        clear_grant(self.request)
        return response
