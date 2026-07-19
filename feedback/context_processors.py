from feedback.forms import PageFeedbackForm


def page_feedback(request):
    """Contexte pied de page : formulaire de retour pour utilisateurs connectés."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {
            "show_page_feedback": False,
            "page_feedback_form": None,
            "page_feedback_page_url": request.get_full_path(),
        }
    return {
        "show_page_feedback": True,
        "page_feedback_form": PageFeedbackForm(initial={"page_url": request.get_full_path()}),
        "page_feedback_page_url": request.get_full_path(),
        "page_feedback_nav_profile": "",
        "page_feedback_nav_profile_label": "",
    }
