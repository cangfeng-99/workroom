"""Wire task writes to the parent status rollup."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Task
from .rollup import refresh_parents


@receiver(post_save, sender=Task, dispatch_uid='projects.task.rollup.save')
def _sync_on_save(sender, instance: Task, **kwargs) -> None:
    refresh_parents(instance)


@receiver(post_delete, sender=Task, dispatch_uid='projects.task.rollup.delete')
def _sync_on_delete(sender, instance: Task, **kwargs) -> None:
    refresh_parents(instance)
