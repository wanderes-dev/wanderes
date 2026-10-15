"""Redirect-only integration for an external partner (dietmed.pt) - not part of the
Wanderes product and never linked from it. Forwards a `codigo` value carried on an
outside link (email, print, ad) to the partner's own page, without the rest of the
app needing to know the partner's URL. No models, no templates, nothing else here.
"""
from urllib.parse import urlencode

from django.http import HttpResponseBadRequest, HttpResponseRedirect

PARTNER_URL = "https://external.dietmed.pt/fishing.asp"


def redirect_to_partner(request):
    """GET ?codigo=X -> 302 to PARTNER_URL?codigo=X.

    The destination host is fixed in code, never taken from the request - only the
    query string is built from it, and urlencode is what keeps a stray newline, `&`
    or `=` in codigo from doing anything but show up as an encoded character.
    """
    codigo = request.GET.get("codigo", "").strip()
    if not codigo:
        return HttpResponseBadRequest("Missing 'codigo' parameter.")
    return HttpResponseRedirect(f"{PARTNER_URL}?{urlencode({'codigo': codigo})}")
