<?php
// Receives the complaints form, forwards it to the Render complaints system,
// and emails the client and the team. If Render can't be reached, the complaint
// is queued on this server and resent later by retry-queue.php – nothing is lost.
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('X-Content-Type-Options: nosniff');
header('Cache-Control: no-store');

function respond(int $status, array $data): void
{
    http_response_code($status);
    echo json_encode($data);
    exit;
}

$lib = dirname(__DIR__) . '/mmc-complaints/complaints-lib.php';
if (!is_file($lib)) {
    respond(500, ['ok' => false, 'message' => 'The complaints service is not set up yet. Please call or email us instead.']);
}
require $lib;
$cfg = mmc_config();

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    respond(405, ['ok' => false, 'message' => 'Method not allowed.']);
}

// --- Spam checks -----------------------------------------------------------
// Hidden field that people never see; bots fill it in.
if (trim((string) ($_POST['website'] ?? '')) !== '') {
    respond(200, ['ok' => true, 'reference' => '']);
}
// Real people take more than a few seconds to fill in the form.
$started = (int) ($_POST['form_started'] ?? 0);
if ($started > 0 && (time() * 1000 - $started) < 4000) {
    respond(429, ['ok' => false, 'message' => 'That was very quick – please check your details and submit again.']);
}
// Limit submissions per internet address.
$ipKey = hash('sha256', ($_SERVER['REMOTE_ADDR'] ?? 'unknown') . date('YmdH'));
$rateFile = mmc_dir('ratelimit') . '/' . $ipKey;
$count = is_file($rateFile) ? (int) file_get_contents($rateFile) : 0;
if ($count >= (int) $cfg['rate_limit_per_hour']) {
    respond(429, ['ok' => false, 'message' => 'Too many submissions from your connection. Please try again later or call us.']);
}

// --- Validation ------------------------------------------------------------
function field(string $name): string
{
    $v = $_POST[$name] ?? '';
    return is_string($v) ? trim(preg_replace('/[^\P{C}\n\t]/u', '', $v) ?? '') : '';
}

$data = [
    'client_name'           => field('client_name'),
    'phone_number'          => field('phone_number'),
    'email_address'         => field('email_address'),
    'nature_of_complaint'   => field('nature_of_complaint'),
    'staff_member_involved' => field('staff_member_involved'),
];

$errors = [];
$len = fn(string $s): int => mb_strlen($s, 'UTF-8');
if ($len($data['client_name']) < 2 || $len($data['client_name']) > 150) {
    $errors['client_name'] = 'Please enter your full name.';
}
if (!preg_match('/^[0-9+()\s.\-]{7,40}$/', $data['phone_number'])) {
    $errors['phone_number'] = 'Please enter a valid phone number.';
}
if (!filter_var($data['email_address'], FILTER_VALIDATE_EMAIL) || $len($data['email_address']) > 254) {
    $errors['email_address'] = 'Please enter a valid email address.';
}
if ($len($data['nature_of_complaint']) < 10 || $len($data['nature_of_complaint']) > 5000) {
    $errors['nature_of_complaint'] = 'Please describe your complaint (10 to 5,000 characters).';
}
if ($len($data['staff_member_involved']) > 150) {
    $errors['staff_member_involved'] = 'Please shorten this to 150 characters.';
}
if (($_POST['consent'] ?? '') !== 'yes') {
    $errors['consent'] = 'Please confirm we may use your details to handle your complaint.';
}
if ($errors) {
    respond(422, ['ok' => false, 'message' => 'Please correct the highlighted fields.', 'errors' => $errors]);
}

@file_put_contents($rateFile, (string) ($count + 1), LOCK_EX);

// --- Forward to Render -----------------------------------------------------
$payload = ['reference' => mmc_new_reference(), 'submitted_at' => date('c')] + $data;

$result = mmc_send_to_render($payload);
if ($result['ok']) {
    $payload['reference'] = $result['reference'];
    mmc_log("Sent {$payload['reference']} to Render");
    $note = 'It has been logged in the complaints register.';
} elseif (mmc_queue_save($payload, $result['error'])) {
    mmc_log("QUEUED {$payload['reference']}: {$result['error']}");
    $note = "NOTE: The complaints register could not be reached ({$result['error']}).\n"
        . 'The complaint is saved on the website server and will be added automatically when the register is back.';
} else {
    mmc_log("FAILED TO QUEUE {$payload['reference']}: {$result['error']}");
    $note = "WARNING: The complaints register could not be reached AND the complaint could not be queued.\n"
        . 'Please add it to the register by hand from the details below.';
}

mmc_alert_team($payload, $note);

$firstName = explode(' ', $payload['client_name'])[0];
mmc_mail(
    $payload['email_address'],
    "We've received your complaint – reference {$payload['reference']}",
    "Dear {$firstName},\n\n"
        . "Thank you for contacting MMC Capital. We have received your complaint and a member of our team will be in touch with you.\n\n"
        . "Your reference number is {$payload['reference']}. Please quote it in any correspondence about this complaint.\n\n"
        . "A copy of what you submitted is below.\n\n"
        . mmc_complaint_summary($payload)
        . "\nKind regards,\nMMC Capital\n",
    mmc_client_reply_to()
);

respond(200, ['ok' => true, 'reference' => $payload['reference']]);
