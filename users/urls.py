from django.urls import path

from . import views
from . import views_push

urlpatterns = [
    path("connexion/", views.login_view, name="account_login"),
    path("connexion/code/", views.login_otp_view, name="account_login_otp"),
    path("connexion/2fa/", views.login_2fa_view, name="account_login_2fa"),
    path("deconnexion/", views.logout_view, name="account_logout"),
    path("", views.account_home, name="account_home"),
    path("guide/terminer/", views.tour_complete, name="account_tour_complete"),
    path("aides/masquer/", views.page_lead_dismiss, name="account_page_lead_dismiss"),
    path("securite/", views.security_view, name="account_security"),
    path("securite/totp/demarrer/", views.totp_setup_start, name="account_totp_start"),
    path("securite/totp/confirmer/", views.totp_setup_confirm, name="account_totp_confirm"),
    path("securite/totp/desactiver/", views.totp_disable, name="account_totp_disable"),
    path("adherent/", views.member_area, name="account_member_area"),
    path("push/vapid-key/", views_push.push_vapid_public_key, name="push_vapid_key"),
    path("push/subscribe/", views_push.push_subscription, name="push_subscribe"),
    path("push/status/", views_push.push_status, name="push_status"),
]
