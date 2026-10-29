"""Tests for deleting library entries."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from apps.projects.models import LibraryEntry, Project


class LibraryDeleteTests(TestCase):
    def setUp(self) -> None:
        self.project = Project.objects.create(name='P', goal_title='上线')
        self.entry = LibraryEntry.objects.create(
            project=self.project,
            kind=LibraryEntry.Kind.RULE,
            title='只做 P0',
            body='范围',
        )

    def test_delete_removes_entry_and_returns_to_library(self) -> None:
        response = self.client.post(
            reverse('projects:library_delete', args=[self.project.pk, self.entry.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('tab=library', response['Location'])
        self.assertFalse(LibraryEntry.objects.filter(pk=self.entry.pk).exists())

    def test_cannot_delete_another_projects_entry(self) -> None:
        other = Project.objects.create(name='Other', goal_title='x')
        response = self.client.post(
            reverse('projects:library_delete', args=[other.pk, self.entry.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(LibraryEntry.objects.filter(pk=self.entry.pk).exists())

    def test_row_has_delete_control(self) -> None:
        url = reverse('projects:space', args=[self.project.pk])
        html = self.client.get(f'{url}?tab=library').content.decode('utf-8')
        self.assertIn('row-del-btn', html)
        self.assertIn('删除资料', html)
