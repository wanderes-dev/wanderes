from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("test-cj-deeplink/", views.test_cj_deeplink, name="test-cj-deeplink"),
    path("health/", views.health_check, name="health-check"),
    path("robots.txt", views.robots_txt, name="robots-txt"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap"),
]
