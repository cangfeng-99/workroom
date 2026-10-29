from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('projects', '0018_tool_connection_instances')]
    operations = [
        migrations.AddField(model_name='task', name='guide', field=models.JSONField(blank=True, default=dict, verbose_name='直白任务说明')),
        migrations.AddField(model_name='task', name='blocked_reason', field=models.TextField(blank=True, verbose_name='现在卡在哪里')),
        migrations.AddField(model_name='task', name='unblock_action', field=models.TextField(blank=True, verbose_name='怎样才能继续')),
        migrations.AddField(model_name='task', name='prerequisites', field=models.ManyToManyField(blank=True, related_name='following_tasks', symmetrical=False, to='projects.task', verbose_name='先要完成的任务')),
    ]
