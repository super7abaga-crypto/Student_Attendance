from django.conf import settings
from django.http import FileResponse, Http404
from django.views.decorators.cache import never_cache


@never_cache
def portal(_request):
    return FileResponse((settings.BASE_DIR / "index.html").open("rb"), content_type="text/html; charset=utf-8")


@never_cache
def asset(request, filename):
    allowed = {"app.js": settings.BASE_DIR / "app.js", "styles.css": settings.BASE_DIR / "styles.css"}
    target = settings.BASE_DIR / "assets" / filename if filename == "learn2earn-logo.svg" else allowed.get(filename)
    if not target or not target.is_file():
        raise Http404
    content_type = "text/css; charset=utf-8" if filename.endswith(".css") else "image/svg+xml" if filename.endswith(".svg") else "text/javascript; charset=utf-8"
    response = FileResponse(target.open("rb"), content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    return response
