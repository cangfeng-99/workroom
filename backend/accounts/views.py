"""Signup, login and logout using Django's built-in auth views."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.views.generic.edit import FormView
from workspaces.grants import clear_grant

from accounts.forms import SignupForm


class SignupView(FormView):
    template_name = 'accounts/signup.html'
    form_class = SignupForm

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        # A new identity must not inherit a folder grant from the session.
        clear_grant(self.request)
        return redirect(settings.LOGIN_REDIRECT_URL)


class AccountLoginView(LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        # Never carry a pre-login folder grant into the authenticated session.
        clear_grant(self.request)
        return response
