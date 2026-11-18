<?php
// MMC Capital complaints – website settings.
// This file lives OUTSIDE public_html so nobody can download it.

date_default_timezone_set('Africa/Harare');

return [
    // Your Render service address, ending in /api/complaints/
    'render_api_url' => 'https://mmc-complaints.onrender.com/api/complaints/',

    // Copy the COMPLAINTS_API_KEY value from Render (service > Environment).
    // Put the real key only in the copy on the server – never commit it to GitHub.
    'render_api_key' => 'PASTE-THE-COMPLAINTS_API_KEY-FROM-RENDER-HERE',

    // Staff portal link included in the alert email to the team.
    'portal_url' => 'https://mmc-complaints.onrender.com/',

    // Who gets the "new complaint" alert.
    'team_emails' => ['complaints@mmccapitalzim.com'],

    // Sender for both emails. Must be a real mailbox on mmccapitalzim.com.
    'from_email' => 'complaints@mmccapitalzim.com',
    'from_name'  => 'MMC Capital Complaints',

    // Spam protection: max complaints from one internet address per hour.
    'rate_limit_per_hour' => 5,
];
