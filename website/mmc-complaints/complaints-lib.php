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
function mmc_send_to_render(array $payload): array
{
    $cfg = mmc_config();
    $ch = curl_init($cfg['render_api_url']);
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
function mmc_queue_save(array $payload, string $lastError): bool
{
    $item = ['payload' => $payload, 'attempts' => 1, 'last_error' => $lastError, 'queued_at' => date('c')];
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
    if ($replyTo && filter_var($replyTo, FILTER_VALIDATE_EMAIL)) {
        $headers[] = 'Reply-To: ' . mmc_header_safe($replyTo);
    }
    $encodedSubject = '=?UTF-8?B?' . base64_encode(mmc_header_safe($subject)) . '?=';
    return @mail(mmc_header_safe($to), $encodedSubject, $body, implode("\r\n", $headers), '-f' . $from);
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
