from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("complaints/", views.complaint_list, name="list"),
    path("complaints/new/", views.complaint_new, name="new"),
    path("enquiries/", views.enquiry_list, name="enquiries"),
    path("complaints/export.csv", views.export_csv, name="export"),
    path("complaints/<str:reference>/", views.complaint_detail, name="detail"),
    path("complaints/<str:reference>/conversation/", views.conversation, name="conversation"),
    path("complaints/<str:reference>/conversation.json", views.conversation_feed, name="conversation_feed"),
    path("conversations/", views.conversations, name="conversations"),
    path("reports/", views.reports, name="reports"),
    path("reports/report.pdf", views.report_pdf, name="report_pdf"),
    path("reports/report.csv", views.report_csv, name="report_csv"),
    path("notifications/", views.notifications, name="notifications"),
    path("notifications/read-all/", views.notifications_read_all, name="notifications_read_all"),
    path("notifications/feed.json", views.notifications_feed, name="notifications_feed"),
    path("notifications/<int:pk>/open/", views.notification_open, name="notification_open"),
]
