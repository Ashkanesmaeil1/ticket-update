"""
URL configuration for ticket_system project.
"""
from django.contrib import admin
from django.urls import path, include

from django.conf import settings
from django.views.static import serve
from django.urls import re_path 
# ------------------------------------------------------------------

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('tickets.urls')),
]

# Serve static files in development
if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns
    urlpatterns += staticfiles_urlpatterns()
else:
    urlpatterns += [
        re_path(r'^static/(?P<path>.*)$', serve, {
            'document_root': settings.STATIC_ROOT,
        }),
    ]

# Serve media files
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {
        'document_root': settings.MEDIA_ROOT,
    }),
]
# ------------------------------------------------------------------


handler400 = 'tickets.views.bad_request'
handler403 = 'tickets.views.permission_denied'
handler404 = 'tickets.views.page_not_found'
handler500 = 'tickets.views.server_error'