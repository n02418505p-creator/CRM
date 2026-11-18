#!/usr/local/bin/php -q
<?php
// Receives client replies sent to replies@cases.mmccapitalzim.com (cPanel pipes each
// email into this script) and adds them to the matching complaint in the portal.
// Must never print anything: any output makes the mail server bounce the email.
declare(strict_types=1);

ob_start();
require __DIR__ . '/complaints-lib.php';
mmc_config();

$raw = (string) stream_get_contents(STDIN, 10 * 1024 * 1024);
if (trim($raw) !== '') {
    $result = mmc_process_inbound($raw);
    if (!$result['ok'] && !$result['permanent']) {
        // Portal unreachable: keep the email and let retry-queue.php try again.
        $file = mmc_dir('inbound-queue') . '/' . date('Ymd-His') . '-' . bin2hex(random_bytes(4)) . '.eml';
        file_put_contents($file, $raw, LOCK_EX);
        @chmod($file, 0600);
        mmc_log('Inbound email queued: ' . $result['error']);
    } elseif (!$result['ok']) {
        mmc_log('Inbound email rejected by the portal: ' . $result['error']);
    }
}
ob_end_clean();
exit(0);
