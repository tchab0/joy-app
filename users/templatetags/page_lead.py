"""Template tags — textes d’aide en haut de page (carte effaçable)."""

from __future__ import annotations

from django import template
from django.template.base import Node, TemplateSyntaxError
from django.template.loader import render_to_string

register = template.Library()


class PageLeadNode(Node):
    def __init__(self, key_expr, nodelist, extra_class: str = ""):
        self.key_expr = key_expr
        self.nodelist = nodelist
        self.extra_class = extra_class

    def render(self, context):
        key = str(self.key_expr.resolve(context) or "").strip()
        if not key:
            return ""
        dismissed = context.get("dismissed_page_leads") or set()
        if key in dismissed:
            return ""
        content = self.nodelist.render(context).strip()
        if not content:
            return ""
        request = context.get("request")
        user = getattr(request, "user", None) if request else None
        can_dismiss = bool(user and getattr(user, "is_authenticated", False))
        return render_to_string(
            "includes/_page_lead.html",
            {
                "lead_key": key,
                "lead_content": content,
                "lead_class": self.extra_class,
                "can_dismiss_lead": can_dismiss,
            },
            request=request,
        )


@register.tag("page_lead")
def do_page_lead(parser, token):
    """
    {% page_lead "planning.dashboard" %}
      Texte d’aide…
    {% endpage_lead %}

    Optionnel : class="page-lead--center"
    """
    bits = token.split_contents()
    if len(bits) < 2:
        raise TemplateSyntaxError(
            f"{bits[0]!r} attend au moins une clé, ex. {{% page_lead \"planning.dashboard\" %}}"
        )
    key_expr = parser.compile_filter(bits[1])
    extra_class = ""
    for bit in bits[2:]:
        if bit.startswith("class="):
            extra_class = bit[len("class=") :].strip("'\"")
        else:
            raise TemplateSyntaxError(
                f"Argument inconnu pour {bits[0]!r} : {bit!r}"
            )
    nodelist = parser.parse(("endpage_lead",))
    parser.delete_first_token()
    return PageLeadNode(key_expr, nodelist, extra_class)
