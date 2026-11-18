"""Who can see what.

- Complaint handlers: complaints only
- Client service: enquiries only
- Administrators (and superusers): everything, including staff accounts
"""
from django.core.exceptions import PermissionDenied

from .models import Complaint

PERMISSION_FOR_TYPE = {
    Complaint.CaseType.COMPLAINT: "complaints.handle_complaints",
    Complaint.CaseType.ENQUIRY: "complaints.handle_enquiries",
}
CODENAME_FOR_TYPE = {
    Complaint.CaseType.COMPLAINT: "handle_complaints",
    Complaint.CaseType.ENQUIRY: "handle_enquiries",
}

ADMIN_GROUP = "Administrators"
COMPLAINTS_GROUP = "Complaint handlers"
CLIENT_SERVICE_GROUP = "Client service"


def can_access(user, case_type):
    return bool(user and user.is_authenticated and (user.is_superuser or user.has_perm(PERMISSION_FOR_TYPE[case_type])))


def allowed_types(user):
    return [t for t in Complaint.CaseType.values if can_access(user, t)]


def require(user, case_type):
    if not can_access(user, case_type):
        raise PermissionDenied


def is_admin(user):
    return bool(user and user.is_authenticated and (user.is_superuser or user.groups.filter(name=ADMIN_GROUP).exists()))


def role_label(user):
    if user.is_superuser or is_admin(user):
        return "Administrator"
    types = allowed_types(user)
    if len(types) == 2:
        return "Complaints & client service"
    if types == [Complaint.CaseType.ENQUIRY]:
        return "Client service"
    if types == [Complaint.CaseType.COMPLAINT]:
        return "Complaint handler"
    return "No case access"
