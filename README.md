# MMC CRM

MMC Capital's client relations system for **complaints** and **enquiries**.

- Clients lodge complaints on **mmccapitalzim.com/complaints.php**, ask questions through **Contact Us**, and request services on the **Advisory** and **Stockbroker Services** pages.
- Every submission lands in the **MMC CRM** at **https://mmc-complaints.onrender.com**. Staff log in there to assign, update, resolve and reply to clients by email.
- Client email replies come back into the CRM as a conversation.

```
                     ┌──────────────────── mmccapitalzim.com (HostGator) ────────────────────┐
 Client ─ complaint ─►  complaints.php ─► submit-complaint.php ─┐                            │
 Client ─ Contact Us / service request ─► submit.php ───────────┤  (queued + retried by cron │
                     │                                          │   if the CRM is down)      │
 Client ─ email reply ─► replies@cases.mmccapitalzim.com ─► mmc-complaints/inbound-email.php │
                     └──────────────────────────────────────────┼────────────────────────────┘
                                                                ▼
                         MMC CRM (Django on Render) ── Postgres
                                                                │
 Client ◄── update emails ◄── complaints-mail.php (sent from the website server) ◄──┘
 Staff  ──► https://mmc-complaints.onrender.com (login, by role)
```

## Features

**Cases**
- **Complaints:** reference `CMP-YYYYMMDD-XXXXXX`. Columns match the paper register: date received, client, phone, email, nature of the complaint, staff member involved, action taken, resolution date, status, remarks.
- **Enquiries:** reference `ENQ-…`. Each one records the enquiry type (general enquiry or service request), division (MMC Capital Advisory or MMC Stockbrokers), service (with the description from the website), organisation, telephone and the page it came from.
- **Statuses:** New → In progress → Resolved → Closed. The resolution date is filled in automatically, and a case open longer than 14 days is flagged **overdue**.
- **Logging a case:** staff log phone, email and walk-in cases in the portal, choosing the service for enquiries.

**Portal**
- **Dashboard:** open, overdue and assigned-to-me counts, cases by status, a six-month trend, enquiries by service, and the latest and my-open cases.
- **Lists:** search, filters (status, assignee, source, dates, enquiry type and service), pagination and **Export to Excel (CSV)**.
- **Case page:** client details, the "what it's about" card for enquiries, status, assignment and handling details.
- **Conversations:** a chat view of every email to and from the client, plus an inbox with **Waiting for us** and **Mine** filters.
- **Notifications:** a bell with an unread count, live pop-ups and optional desktop alerts. They cover new cases, assignments, status changes and client replies.
- **Look:** MMC branding, light and dark themes, and a layout that works on phones, with a menu button and a fixed sign-in screen that shows the logo.

**Email**
- **To clients:** a confirmation with the reference number, plus updates on status changes, on assignment and when staff send a message. Each update includes the current status, who is handling the case and the earlier messages.
- **From clients:** replies go to `research@` and to `replies@cases.mmccapitalzim.com`, which files them in the CRM. Quoted earlier emails, Outlook image placeholders and out-of-office replies are removed or ignored.

## Roles

| Group | Access |
|---|---|
| **Complaint handlers** | Complaints only |
| **Client service** | Enquiries only |
| **Administrators** | Everything, plus **Manage staff** (staff status is given automatically) |

Superusers have full access. Lists, case pages, conversations, exports, search, the dashboard, the assignment list and new-case notifications all follow the person's role. Groups are created and updated on every deploy by `python manage.py setup_complaints`.

**Adding staff:** sign in as an administrator, open **Manage staff → Add user**, then choose their group or groups and save.

## Repository layout

| Path | What it is |
|---|---|
| `config/` | Django settings and URLs |
| `complaints/` | The CRM app: models, views, API, roles, emails, templates and static files |
| `complaints/enquiries.py` | Service list (with descriptions) and parser for website enquiries |
| `complaints/tests.py` | Automated tests (run on every push by GitHub Actions) |
| `render.yaml`, `build.sh`, `requirements.txt` | Render deployment |
| `website/public_html/` | Files in the website's `public_html` (`complaints.php`, `submit-complaint.php`, `complaints-mail.php`) |
| `website/mmc-complaints/` | Private website files that sit **next to** `public_html`: `config.php`, `complaints-lib.php`, `retry-queue.php`, `inbound-email.php` |

## Deployment (Render)

- **Services:** the `render.yaml` blueprint creates **mmc-complaints**, the web service (Starter plan, always on), and **mmc-complaints-db** (Postgres, Basic 256 MB), both in Frankfurt.
- **Releases:** every push to `main` deploys automatically. The build runs `migrate` and `setup_complaints`. Render reads this repository by its public URL, so the repository must stay **public**. It contains no passwords, keys or client data.
- **Workflow:** work on a branch, wait for the GitHub Actions **tests** to pass, then merge to `main`.

**Environment variables** (Render → mmc-complaints → Environment)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django secret (generated) |
| `DATABASE_URL` | Postgres connection (from the database) |
| `COMPLAINTS_API_KEY` | Shared key between the website and the CRM; also goes in `mmc-complaints/config.php` on the website |
| `ADMIN_USERNAME` / `ADMIN_EMAIL` / `ADMIN_PASSWORD` | First administrator, created on the first deploy |
| `COMPLAINT_TARGET_DAYS` | Days before an open case is overdue (default 14) |
| `MAIL_RELAY_URL` | Website script that sends CRM emails (default `https://www.mmccapitalzim.com/complaints-mail.php`) |
| `COMPLAINTS_REPLY_TO` | Reply-To addresses for client emails (default `research@mmccapitalzim.com,replies@cases.mmccapitalzim.com`) |
| `BRAND_LOGO_URL` / `BRAND_ICON_BASE` | Logo and browser icons (loaded from mmccapitalzim.com) |
| `ALLOWED_HOSTS` | Extra host names, e.g. a custom domain |

## Website setup (HostGator / cPanel)

1. **Private folder:** upload `website/mmc-complaints/*` to `/home1/xqqdbvte/mmc-complaints/`. In `config.php`, set `render_api_url`, `render_api_key` (the `COMPLAINTS_API_KEY`), `portal_url`, `team_emails` and `from_email`. Keep the real key only on the server.
2. **Public files:** upload `website/public_html/*` to `public_html` (and to the preview site if needed). `complaints.php` takes its header, navigation and footer from the site's own `contact.html`.
3. **Contact Us:** `submit.php` calls `mmc_record_enquiry()` after its checks, so each message is logged in the CRM as an enquiry. The email to research@ is unchanged. Service request forms post to the same script.
4. **Cron** (every 15 minutes): `php /home1/xqqdbvte/mmc-complaints/retry-queue.php >/dev/null 2>&1`. It resends anything queued while the CRM was unreachable.
5. **Client replies:**
   - The subdomain `cases.mmccapitalzim.com` has its MX record pointing at the server, with email routing set to *local*.
   - The forwarder `replies@cases.mmccapitalzim.com` pipes to `mmc-complaints/inbound-email.php`, which must be executable (`755`).
6. **Email authentication for mmccapitalzim.com:**
   - SPF: `v=spf1 ip4:50.6.160.183 include:spf.protection.outlook.com -all`.
   - DKIM: a single `default._domainkey` record. cPanel → Email Deliverability should show it as valid.
   - Microsoft 365 email is not affected.

Logs are in `mmc-complaints/logs/complaints-YYYY-MM.log`. Queued items are in `queue/` and `inbound-queue/`, and items that failed permanently are in `failed/`.

## API (used by the website)

All endpoints need the `X-API-Key` header.

| Endpoint | Body (JSON) |
|---|---|
| `POST /api/complaints/` | `reference`, `submitted_at`, `client_name`, `phone_number`, `email_address`, `nature_of_complaint`, `staff_member_involved` |
| `POST /api/enquiries/` | `reference`, `submitted_at`, `client_name`, `email_address`, `phone_number`, `subject`, `message`, optional `enquiry_type`, `division`, `service`, `organisation`, `enquiry_about` (`division\|topic`) |
| `POST /api/complaints/inbound/` | `from_email`, `from_name`, `subject`, `text`, `message_id` (client replies) |

Re-sending the same `reference` or `message_id` never creates duplicates. `GET /healthz` is used for Render health checks.

## Developing locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DEBUG=true COMPLAINTS_API_KEY=dev EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
python manage.py migrate && python manage.py setup_complaints && python manage.py createsuperuser
python manage.py test        # run the tests
python manage.py runserver   # http://localhost:8000
```
