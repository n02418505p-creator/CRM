<?php
// Shared functions for submit-complaint.php and retry-queue.php.
declare(strict_types=1);

const MMC_DIR = __DIR__;

function mmc_config(): array
{
    static $config = null;
    if ($config === null) {
        $config = require MMC_DIR . '/config.php';
    }
    return $config;
}

function mmc_dir(string $name): string
{
    $dir = MMC_DIR . '/' . $name;
    if (!is_dir($dir)) {
        @mkdir($dir, 0700, true);
    }
    return $dir;
}

function mmc_new_reference(): string
{
    return 'CMP-' . date('Ymd') . '-' . strtoupper(bin2hex(random_bytes(3)));
}

/**
 * Send one complaint to Render.
 * Returns ['ok' => bool, 'reference' => ?string, 'permanent' => bool, 'error' => string].
 * 'permanent' means resending will never work (Render rejected the data itself).
 */
function mmc_send_to_render(array $payload, ?string $url = null): array
{
    $cfg = mmc_config();
    $ch = curl_init($url ?? $cfg['render_api_url']);
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => json_encode($payload, JSON_UNESCAPED_UNICODE),
        CURLOPT_HTTPHEADER     => [
            'Content-Type: application/json',
            'Accept: application/json',
            'X-API-Key: ' . $cfg['render_api_key'],
        ],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_TIMEOUT        => 25,
    ]);
    $body = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $curlError = curl_error($ch);
    curl_close($ch);

    if ($body === false) {
        return ['ok' => false, 'reference' => null, 'permanent' => false, 'error' => 'Connection failed: ' . $curlError];
    }
    $json = json_decode((string) $body, true);
    if (($status === 200 || $status === 201) && is_array($json) && !empty($json['ok'])) {
        return ['ok' => true, 'reference' => (string) $json['reference'], 'permanent' => false, 'error' => ''];
    }
    return [
        'ok'        => false,
        'reference' => null,
        'permanent' => $status === 400,
        'error'     => "HTTP $status: " . substr((string) $body, 0, 500),
    ];
}

/** Save a complaint that could not be sent, so retry-queue.php can resend it. */
function mmc_queue_save(array $payload, string $lastError, ?string $url = null): bool
{
    $item = ['payload' => $payload, 'attempts' => 1, 'last_error' => $lastError, 'queued_at' => date('c'), 'url' => $url];
    $file = mmc_dir('queue') . '/' . $payload['reference'] . '.json';
    $ok = file_put_contents($file, json_encode($item, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE), LOCK_EX) !== false;
    if ($ok) {
        @chmod($file, 0600);
    }
    return $ok;
}

function mmc_log(string $message): void
{
    @file_put_contents(mmc_dir('logs') . '/complaints-' . date('Y-m') . '.log', '[' . date('c') . "] $message\n", FILE_APPEND | LOCK_EX);
}

/** Remove anything that could inject extra email headers. */
function mmc_header_safe(string $value): string
{
    return trim(str_replace(["\r", "\n", "\0"], ' ', $value));
}

function mmc_mail(string $to, string $subject, string $body, ?string $replyTo = null): bool
{
    $cfg = mmc_config();
    $from = mmc_header_safe($cfg['from_email']);
    $fromName = '=?UTF-8?B?' . base64_encode(mmc_header_safe($cfg['from_name'])) . '?=';
    $headers = [
        'From: ' . $fromName . ' <' . $from . '>',
        'MIME-Version: 1.0',
        'Content-Type: text/plain; charset=UTF-8',
        'Content-Transfer-Encoding: 8bit',
    ];
    if ($replyTo) {
        $valid = array_filter(array_map('trim', explode(',', $replyTo)), fn($a) => (bool) filter_var($a, FILTER_VALIDATE_EMAIL));
        if ($valid) {
            $headers[] = 'Reply-To: ' . mmc_header_safe(implode(', ', $valid));
        }
    }
    $encodedSubject = '=?UTF-8?B?' . base64_encode(mmc_header_safe($subject)) . '?=';
    $ok = @mail(mmc_header_safe($to), $encodedSubject, $body, implode("\r\n", $headers), '-f' . $from);
    if (!$ok) {
        mmc_log('mail() failed for ' . mmc_header_safe($to) . ': ' . mmc_header_safe($subject));
    }
    return $ok;
}

function mmc_complaint_summary(array $p): string
{
    return "Reference:              {$p['reference']}\n"
        . "Date received:          " . date('j F Y, H:i', strtotime($p['submitted_at'])) . "\n"
        . "Client name:            {$p['client_name']}\n"
        . "Phone number:           {$p['phone_number']}\n"
        . "Email address:          {$p['email_address']}\n"
        . "Staff member involved:  " . ($p['staff_member_involved'] !== '' ? $p['staff_member_involved'] : '(not given)') . "\n\n"
        . "Nature of the complaint:\n{$p['nature_of_complaint']}\n";
}

function mmc_alert_team(array $payload, string $note): void
{
    $cfg = mmc_config();
    $body = "A new complaint was submitted on the MMC Capital website.\n\n"
        . $note . "\n\n"
        . mmc_complaint_summary($payload)
        . "\nOpen the complaints register: {$cfg['portal_url']}\n";
    foreach ($cfg['team_emails'] as $to) {
        mmc_mail($to, "New complaint {$payload['reference']} – {$payload['client_name']}", $body, $payload['email_address']);
    }
}


/** Reply-To for emails to clients: the team inbox plus the address that files replies into the portal. */
function mmc_client_reply_to(): string
{
    $cfg = mmc_config();
    return $cfg['client_reply_to'] ?? (($cfg['team_emails'][0] ?? 'research@mmccapitalzim.com') . ', replies@cases.mmccapitalzim.com');
}

// ---------------------------------------------------------------------------
// Inbound email (client replies piped in by cPanel)
// ---------------------------------------------------------------------------

function mmc_inbound_url(): string
{
    $cfg = mmc_config();
    return $cfg['render_inbound_url'] ?? preg_replace('~/api/complaints/?$~', '/api/complaints/inbound/', $cfg['render_api_url']);
}

/** Split a raw message into [lower-case header map, body]. */
function mmc_parse_part(string $raw): array
{
    $raw = str_replace("\r\n", "\n", $raw);
    $pos = strpos($raw, "\n\n");
    $head = $pos === false ? $raw : substr($raw, 0, $pos);
    $body = $pos === false ? '' : substr($raw, $pos + 2);
    $head = preg_replace("/\n[ \t]+/", ' ', $head);   // unfold continued header lines
    $headers = [];
    foreach (explode("\n", (string) $head) as $line) {
        if (strpos($line, ':') === false) {
            continue;
        }
        [$name, $value] = explode(':', $line, 2);
        $name = strtolower(trim($name));
        if (!isset($headers[$name])) {
            $headers[$name] = trim($value);
        }
    }
    return [$headers, $body];
}

function mmc_decode_header_value(string $value): string
{
    if (function_exists('iconv_mime_decode')) {
        $decoded = @iconv_mime_decode($value, ICONV_MIME_DECODE_CONTINUE_ON_ERROR, 'UTF-8');
        if ($decoded !== false) {
            return $decoded;
        }
    }
    return function_exists('mb_decode_mimeheader') ? mb_decode_mimeheader($value) : $value;
}

function mmc_header_param(string $header, string $param): string
{
    if (preg_match('/' . preg_quote($param, '/') . '\s*=\s*"([^"]*)"/i', $header, $m)
        || preg_match('/' . preg_quote($param, '/') . '\s*=\s*([^;\s]+)/i', $header, $m)) {
        return $m[1];
    }
    return '';
}

function mmc_decode_body(string $body, array $headers): string
{
    $encoding = strtolower($headers['content-transfer-encoding'] ?? '');
    if ($encoding === 'base64') {
        $body = (string) base64_decode(preg_replace('/\s+/', '', $body));
    } elseif ($encoding === 'quoted-printable') {
        $body = quoted_printable_decode($body);
    }
    $charset = strtoupper(mmc_header_param($headers['content-type'] ?? '', 'charset')) ?: 'UTF-8';
    if ($charset !== 'UTF-8' && $charset !== 'US-ASCII' && function_exists('mb_convert_encoding')) {
        $converted = @mb_convert_encoding($body, 'UTF-8', $charset);
        if (is_string($converted)) {
            $body = $converted;
        }
    }
    return $body;
}

function mmc_html_to_text(string $html): string
{
    $html = preg_replace('~<(style|script|head)[^>]*>.*?</\1>~is', '', $html);
    $html = preg_replace('~<blockquote.*?</blockquote>~is', '', $html);   // quoted earlier emails
    $html = preg_replace('~<br\s*/?>|</p>|</div>|</tr>|</li>~i', "\n", $html);
    $text = html_entity_decode(strip_tags($html), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    $text = preg_replace("/[ \t]+/", ' ', $text);
    return trim(preg_replace("/\n\s*\n\s*\n+/", "\n\n", $text));
}

/** Find the readable text of an email: plain text if there is one, otherwise converted HTML. */
function mmc_extract_text(array $headers, string $body, int $depth = 0): array
{
    $type = strtolower(trim(explode(';', $headers['content-type'] ?? 'text/plain')[0]));
    if (strpos($type, 'multipart/') === 0 && $depth < 5) {
        $boundary = mmc_header_param($headers['content-type'] ?? '', 'boundary');
        if ($boundary === '') {
            return ['', ''];
        }
        $plain = '';
        $html = '';
        foreach (explode('--' . $boundary, $body) as $chunk) {
            $chunk = ltrim($chunk, "\n");
            if ($chunk === '' || strpos($chunk, '--') === 0) {
                continue;
            }
            [$h, $b] = mmc_parse_part($chunk);
            if (stripos($h['content-disposition'] ?? '', 'attachment') !== false) {
                continue;
            }
            [$p, $x] = mmc_extract_text($h, $b, $depth + 1);
            $plain = $plain !== '' ? $plain : $p;
            $html = $html !== '' ? $html : $x;
        }
        return [$plain, $html];
    }
    if ($type === 'text/plain') {
        return [mmc_decode_body($body, $headers), ''];
    }
    if ($type === 'text/html') {
        return ['', mmc_decode_body($body, $headers)];
    }
    return ['', ''];
}

/**
 * Turn a raw email into the data the portal needs and send it.
 * Returns ['ok' => bool, 'permanent' => bool, 'skipped' => bool, 'error' => string].
 */
function mmc_process_inbound(string $raw): array
{
    [$headers, $body] = mmc_parse_part($raw);

    // Ignore out-of-office and other automatic replies so they don't clutter complaints.
    $auto = strtolower($headers['auto-submitted'] ?? 'no');
    $precedence = strtolower($headers['precedence'] ?? '');
    if (($auto !== '' && $auto !== 'no') || isset($headers['x-autoreply']) || isset($headers['x-autorespond'])
        || in_array($precedence, ['bulk', 'junk', 'list', 'auto_reply'], true)) {
        return ['ok' => true, 'permanent' => false, 'skipped' => true, 'error' => 'automatic reply ignored'];
    }

    $from = mmc_decode_header_value($headers['from'] ?? '');
    $fromName = '';
    $fromEmail = trim($from);
    if (preg_match('/^(.*)<([^>]+)>/', $from, $m)) {
        $fromName = trim($m[1], " \t\"'");
        $fromEmail = trim($m[2]);
    }
    [$plain, $html] = mmc_extract_text($headers, $body);
    $text = trim($plain !== '' ? $plain : mmc_html_to_text($html));

    $payload = [
        'from_email' => strtolower($fromEmail),
        'from_name'  => $fromName,
        'subject'    => mmc_decode_header_value($headers['subject'] ?? ''),
        'text'       => mb_substr($text, 0, 50000),
        'message_id' => trim($headers['message-id'] ?? ''),
    ];

    $cfg = mmc_config();
    $ch = curl_init(mmc_inbound_url());
    curl_setopt_array($ch, [
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_INVALID_UTF8_SUBSTITUTE),
        CURLOPT_HTTPHEADER     => ['Content-Type: application/json', 'X-API-Key: ' . $cfg['render_api_key']],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_TIMEOUT        => 25,
    ]);
    $response = curl_exec($ch);
    $status = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    $json = json_decode((string) $response, true);
    if ($status === 200 && is_array($json) && !empty($json['ok'])) {
        $matched = !empty($json['matched']);
        mmc_log('Inbound email from ' . $payload['from_email'] . ($matched ? ' added to ' . ($json['reference'] ?? '?') : ' did not match a complaint'));
        return ['ok' => true, 'permanent' => false, 'skipped' => !$matched, 'error' => ''];
    }
    return ['ok' => false, 'permanent' => $status === 400, 'skipped' => false, 'error' => "HTTP $status"];
}


// ---------------------------------------------------------------------------
// Enquiries from the Contact Us form
// ---------------------------------------------------------------------------

function mmc_enquiries_url(): string
{
    $cfg = mmc_config();
    return $cfg['render_enquiries_url'] ?? preg_replace('~/api/complaints/?$~', '/api/enquiries/', $cfg['render_api_url']);
}

/** Log a Contact Us message in the CRM. Never throws; queues it if the CRM can't be reached. */
function mmc_record_enquiry(string $name, string $email, string $subject, string $message, string $phone = ''): ?string
{
    try {
        $payload = [
            'reference'     => 'ENQ-' . date('Ymd') . '-' . strtoupper(bin2hex(random_bytes(3))),
            'submitted_at'  => date('c'),
            'client_name'   => mb_substr(trim($name), 0, 150),
            'email_address' => trim($email),
            'phone_number'  => mb_substr(trim($phone), 0, 40),
            'subject'       => mb_substr(trim($subject), 0, 200),
            'message'       => mb_substr(trim($message), 0, 5000),
        ];
        $url = mmc_enquiries_url();
        $result = mmc_send_to_render($payload, $url);
        if ($result['ok']) {
            mmc_log("Enquiry {$result['reference']} sent to the CRM");
            return $result['reference'];
        }
        if (!$result['permanent'] && mmc_queue_save($payload, $result['error'], $url)) {
            mmc_log("Enquiry {$payload['reference']} QUEUED: {$result['error']}");
            return $payload['reference'];
        }
        mmc_log("Enquiry from {$payload['email_address']} could not be logged: {$result['error']}");
    } catch (Throwable $e) {
        mmc_log('Enquiry logging error: ' . $e->getMessage());
    }
    return null;
}
