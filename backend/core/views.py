from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET


# Read-only liveness: GET only, writes nothing, so CSRF does not apply here.
@csrf_exempt
@require_GET
def health(request):
    """Liveness probe: the service answers, nothing more."""
    return JsonResponse({'status': 'ok', 'service': 'agentworkspace'})


@never_cache
def home(request):
    return render(request, 'core/home.html')
