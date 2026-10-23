"""A project owned by one user; its folder is only a remembered location."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Project(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='projects'
    )
    name = models.CharField(max_length=120)
    description = models.TextField(max_length=2000, blank=True)
    workspace_path = models.CharField(max_length=1024, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-updated_at', '-pk')

    def __str__(self) -> str:
        return self.name
