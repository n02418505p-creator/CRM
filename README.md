# MMC Capital – Complaints Register

Clients lodge complaints on **mmccapitalzim.com/complaints.php**. Each complaint is
sent automatically to this complaints system on **Render**, where staff log in to
view, assign, update and close it.

```
Client ──► complaints.php (HostGator) ──► submit-complaint.php ──► Render API ──► Postgres
                                              │                                    ▲
                                              ├─ emails client + team              │
                                              └─ if Render is down: queue ── retry-queue.php (cron)
Staff ──► https://<your-service>.onrender.com  (login) ────────────────────────────┘
```

The register uses the same columns as the existing register: Date Received, Client Name,
Phone Number, Email Address, Nature of the Complaint, Staff Member Involved, Action Taken,
Resolution Date, Status, Remarks. It also adds a reference number, *Assigned to*,
*Source* (website, phone, walk-in…) and *Days open*.

## What's in this repository

| Path | What it is |
|---|---|
| `config/`, `complaints/`, `manage.py` | The Django app that runs on Render (staff portal + API) |
| `render.yaml`, `build.sh`, `requirements.txt` | Render setup |
| `website/public_html/` | Files to upload to the website's `public_html` folder |
| `website/mmc-complaints/` | Private files to upload to the home folder, **next to** `public_html` (not inside it) |

---

## 1. Deploy to Render (about 10 minutes)

1. In Render, click **New → Blueprint** and connect the GitHub repository **n02418505p-creator/CRM**.
2. Render reads `render.yaml` and will create:
   - **mmc-complaints**: web service (Starter, about $7/month, always on)
   - **mmc-complaints-db**: Postgres database (Basic 256 MB, about $6/month, backed up, does not expire)
3. When asked, fill in:
   - `ADMIN_USERNAME`: your login name, e.g. `takudzwa`
   - `ADMIN_EMAIL`: your email address
   - `ADMIN_PASSWORD`: a strong password (10+ characters)
4. Click **Apply** and wait for the deploy to finish (green **Live**).
5. Open the service URL (e.g. `https://mmc-complaints.onrender.com`) and log in.
6. Go to the service's **Environment** tab and copy the value of **`COMPLAINTS_API_KEY`**.
   You'll need it in step 2.

> After the first deploy you can delete `ADMIN_PASSWORD` from the Environment tab;
> the account has already been created. Change your password in the portal.

## 2. Install on the website (HostGator)

Try it on **preview.mmccapitalzim.com** first, then repeat for the live site.

1. Edit `website/mmc-complaints/config.php`:
   - `render_api_url`: your Render URL + `/api/complaints/`
   - `render_api_key`: the `COMPLAINTS_API_KEY` from step 1.6
   - `portal_url`: your Render URL
   - `team_emails` / `from_email`: real mailboxes on mmccapitalzim.com
     (create `complaints@mmccapitalzim.com` in cPanel → Email Accounts, or use an existing one)
2. In cPanel **File Manager**, in your home folder (`/home1/xqqdbvte`), create the folder
   **`mmc-complaints`** (beside `public_html`, *not inside it*) and upload
   `config.php`, `complaints-lib.php` and `retry-queue.php` into it.
3. Upload `complaints.php` and `submit-complaint.php` into **`public_html`**
   (or `preview.mmccapitalzim.com` for testing). The page automatically reuses the
   navigation, footer and styling of `contact.html`.
4. In cPanel → **Cron Jobs**, add a job that runs **every 15 minutes**:
   ```
   php /home1/xqqdbvte/mmc-complaints/retry-queue.php
   ```
5. Add a **"Complaints"** link to the site, e.g. in the footer or on the Contact page, pointing to `complaints.php`.
6. Submit a test complaint. You should get the confirmation email, the team should get an
   alert, and the complaint should appear in the portal.

## 3. Add staff

In the portal: **Users → Add user**. After saving:
- tick **Staff status** (lets them log in)
- add them to the group **Complaint handlers** (can view, add and edit complaints but not delete)
- tick **Superuser status** only for people who should manage users

## Using the portal

- **Filter** by open/closed, status, assignee, source or date. **Search** across name, phone, email, reference and text.
- **Phone or walk-in complaints:** click *Add complaint* and set *Source*.
- **Bulk actions:** select rows → *Mark as In progress / Resolved / Closed* or *Export to Excel (CSV)*.
- The **resolution date** fills in automatically when a complaint is set to Resolved or Closed.
- Every change is recorded: open a complaint and click **History** to see who changed what and when.

## Optional: a nicer portal address

Render → service → **Settings → Custom Domains** → add `complaints.mmccapitalzim.com`,
then add the CNAME record it shows in cPanel → **Zone Editor**. Then add an environment
variable `ALLOWED_HOSTS=complaints.mmccapitalzim.com` and update `config.php` to use the new address.

## Developing locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DEBUG=true COMPLAINTS_API_KEY=dev
python manage.py migrate && python manage.py createsuperuser
python manage.py test        # run the tests
python manage.py runserver   # http://localhost:8000
```
