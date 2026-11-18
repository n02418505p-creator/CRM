from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("complaints", "0005_enquiries"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="complaint",
            options={
                "ordering": ["-date_received"],
                "permissions": [
                    ("handle_complaints", "Can work on complaints"),
                    ("handle_enquiries", "Can work on enquiries"),
                ],
            },
        ),
    ]
