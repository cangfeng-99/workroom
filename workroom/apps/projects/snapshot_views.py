"""Small read-only change signal; clients never reload an edited form silently."""
import hashlib
import json

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .permissions import project_for


@require_GET
def snapshot(request, pk):
    project = project_for(request, pk)
    state = {
        'context':project.context_revision,
        'tasks':list(project.tasks.order_by('pk').values_list('pk','status','assignee_id','title')),
        'message':project.messages.order_by('-pk').values_list('pk',flat=True).first(),
        'members':list(project.members.order_by('pk').values_list('pk','is_active','name')),
        'delivery':list(project.tasks.values_list('deliveries__pk','deliveries__status')),
    }
    version = hashlib.sha256(json.dumps(state,ensure_ascii=False).encode()).hexdigest()[:24]
    result = JsonResponse({'version':version})
    result['Cache-Control']='no-store'
    return result
