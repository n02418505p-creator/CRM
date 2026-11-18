<?php
// Resends complaints that could not reach Render at the time they were submitted.
// Run from a cPanel cron job every 15 minutes:
//   php /home1/xqqdbvte/mmc-complaints/retry-queue.php
declare(strict_types=1);

if (PHP_SAPI !== 'cli') {
    http_response_code(403);
    exit("Run this from cron.\n");
}

require __DIR__ . '/complaints-lib.php';
mmc_config();

$files = glob(mmc_dir('queue') . '/*.json') ?: [];
foreach ($files as $file) {
    $item = json_decode((string) file_get_contents($file), true);
    if (!is_array($item) || !isset($item['payload']['reference'])) {
        rename($file, mmc_dir('failed') . '/' . basename($file));
        continue;
    }
    $ref = $item['payload']['reference'];
    $result = mmc_send_to_render($item['payload']);

    if ($result['ok']) {
        unlink($file);
        mmc_log("Resent $ref to Render");
        echo "Sent $ref\n";
    } elseif ($result['permanent']) {
        rename($file, mmc_dir('failed') . '/' . basename($file));
        mmc_log("Render rejected $ref: {$result['error']}");
        mmc_alert_team($item['payload'], "WARNING: The complaints register rejected this complaint ({$result['error']}).\nPlease add it by hand.");
        echo "Rejected $ref\n";
    } else {
        $item['attempts'] = (int) ($item['attempts'] ?? 0) + 1;
        $item['last_error'] = $result['error'];
        file_put_contents($file, json_encode($item, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE), LOCK_EX);
        // Tell the team once a day-ish if something has been stuck for a while.
        if ($item['attempts'] % 96 === 0) {
            mmc_alert_team($item['payload'], "Still waiting: this complaint has not reached the register after {$item['attempts']} attempts ({$result['error']}).");
        }
        echo "Still queued $ref ({$result['error']})\n";
    }
}

// Client replies that could not reach the portal.
foreach (glob(mmc_dir('inbound-queue') . '/*.eml') ?: [] as $file) {
    $result = mmc_process_inbound((string) file_get_contents($file));
    if ($result['ok'] || $result['permanent']) {
        unlink($file);
        echo "Inbound email processed: " . basename($file) . "\n";
    } else {
        echo "Inbound email still queued: " . basename($file) . " ({$result['error']})\n";
    }
}

// Tidy old rate-limit counters.
foreach (glob(mmc_dir('ratelimit') . '/*') ?: [] as $f) {
    if (filemtime($f) < time() - 7200) {
        @unlink($f);
    }
}
