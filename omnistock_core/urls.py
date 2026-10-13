from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect, render
from django.http import HttpResponse, FileResponse
import os

def service_worker(request):
    sw_path = os.path.join(settings.BASE_DIR, 'static', 'serviceworker.js')
    response = FileResponse(open(sw_path, 'rb'), content_type='application/javascript')
    # Allow the service worker to control the whole domain scope
    response['Service-Worker-Allowed'] = '/'
    return response

def manifest_json(request):
    manifest_path = os.path.join(settings.BASE_DIR, 'static', 'manifest.json')
    return FileResponse(open(manifest_path, 'rb'), content_type='application/manifest+json')

def offline_view(request):
    return render(request, 'offline.html')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('inventory/', include('inventory.urls')),
    path('pos/', include('pos.urls')),
    path('repair/', include('repair.urls')),
    path('finance/', include('finance.urls')),
    path('serviceworker.js', service_worker, name='serviceworker'),
    path('manifest.json', manifest_json, name='manifest'),
    path('offline/', offline_view, name='offline'),
    path('', lambda request: redirect('pos:terminal')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
