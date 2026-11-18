<?php
// Sends emails on behalf of the complaints portal (on Render). This server is
// authorised to send email for mmccapitalzim.com, so portal emails go out from here.
// Protected by the same API key the website uses to send complaints to the portal.
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function reply(int $status, array $data): void
{
    http_response_code($status);
    echo json_encode($data);
    exit;
}

$lib = dirname(__DIR__) . '/mmc-complaints/complaints-lib.php';
if (!is_file($lib)) {
    reply(500, ['ok' => false, 'error' => 'not configured']);
}
require $lib;
$cfg = mmc_config();

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    reply(405, ['ok' => false, 'error' => 'method not allowed']);
}
$key = (string) ($_SERVER['HTTP_X_API_KEY'] ?? '');
if ($cfg['render_api_key'] === '' || !hash_equals((string) $cfg['render_api_key'], $key)) {
    reply(401, ['ok' => false, 'error' => 'unauthorised']);
}

$data = json_decode((string) file_get_contents('php://input'), true);
if (!is_array($data)) {
    reply(400, ['ok' => false, 'error' => 'invalid JSON']);
}
$to = trim((string) ($data['to'] ?? ''));
$subject = trim((string) ($data['subject'] ?? ''));
$body = (string) ($data['body'] ?? '');
$replyTo = trim((string) ($data['reply_to'] ?? '')) ?: ($cfg['team_emails'][0] ?? null);

if (!filter_var($to, FILTER_VALIDATE_EMAIL) || $subject === '' || $body === '' || strlen($body) > 50000 || mb_strlen($subject) > 200) {
    reply(400, ['ok' => false, 'error' => 'invalid message']);
}

$ok = mmc_mail($to, $subject, $body, $replyTo);
mmc_log(($ok ? 'Portal email sent to ' : 'Portal email FAILED to ') . $to . ': ' . $subject);
reply($ok ? 200 : 502, $ok ? ['ok' => true] : ['ok' => false, 'error' => 'the mail server did not accept the message']);
