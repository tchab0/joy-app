from __future__ import annotations

import json

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from stats.services import build_dashboard_context, resolve_period


@staff_member_required
def dashboard(request):
    period = resolve_period(request.GET.get("period"))
    ctx = build_dashboard_context(
        period=period,
        ga_id=getattr(settings, "GA_MEASUREMENT_ID", "") or "",
    )
    # Séries pour Chart.js
    ctx["charts_json"] = json.dumps(
        {
            "contacts": ctx["visitors"]["contact_series"],
            "chat": ctx["musicians"]["chat_series"],
            "usage": ctx["usage"]["series"],
            "features": [
                {"label": f["label"], "count": f["count"]}
                for f in ctx["usage"]["ranking"][:12]
            ],
            "login_buckets": ctx["musicians"]["login_buckets"],
            "participation": [
                {"label": p["label"], "count": p["count"]}
                for p in ctx["musicians"]["participation_by_status"]
            ],
        },
        ensure_ascii=False,
    )
    return render(request, "stats/dashboard.html", ctx)
