from django.db import migrations


def fill(apps, schema_editor):
    """Read service, organisation and phone out of enquiries that already exist."""
    from complaints.enquiries import parse, service_info

    Complaint = apps.get_model("complaints", "Complaint")
    for c in Complaint.objects.filter(case_type="enquiry"):
        info = parse(c.subject, c.nature_of_complaint)
        if not info:
            continue
        c.enquiry_type = c.enquiry_type or info.get("enquiry_type", "")
        c.division = c.division or info.get("division", "")
        c.service = c.service or info.get("service", "")
        c.organisation = c.organisation or info.get("organisation", "")
        c.phone_number = c.phone_number or info.get("phone_number", "")
        c.source_page = c.source_page or info.get("source_page", "")
        if info.get("message"):
            c.nature_of_complaint = info["message"]
        if info.get("subject"):
            c.subject = info["subject"]
        known = service_info(c.service)
        if known:
            c.division, c.service = known[0], known[1]
        c.save()


class Migration(migrations.Migration):
    dependencies = [
        ("complaints", "0007_enquiry_details"),
    ]

    operations = [
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]
