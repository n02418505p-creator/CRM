<?php
// Complaints page. It reuses contact.html's navigation, footer and styling,
// so it always matches the rest of the site, and swaps in the complaints form.
declare(strict_types=1);

$form = <<<'HTML'
        <!-- Header Start -->
        <div class="container-fluid bg-breadcrumb">
            <div class="bg-breadcrumb-single"></div>
            <div class="container text-center py-5" style="max-width: 900px;">
                <h4 class="text-white display-4 mb-4 wow fadeInDown" data-wow-delay="0.1s">Complaints</h4>
                <ol class="breadcrumb justify-content-center mb-0 wow fadeInDown" data-wow-delay="0.3s">
                    <li class="breadcrumb-item"><a href="index.html">Home</a></li>
                    <li class="breadcrumb-item"><a href="contact.html">Contact</a></li>
                    <li class="breadcrumb-item active text-primary">Complaints</li>
                </ol>
            </div>
        </div>
        <!-- Header End -->

        <!-- Complaints Start -->
        <div class="container-fluid contact bg-light py-5">
            <div class="container py-5">
                <div class="row g-5">
                    <div class="col-lg-5 wow fadeInLeft" data-wow-delay="0.1s">
                        <h4 class="text-primary">Lodge a Complaint</h4>
                        <h1 class="display-6 mb-4">We want to hear from you</h1>
                        <p class="mb-4">If you are unhappy with any service you have received from MMC Capital, or with the conduct of any of our staff, please let us know using this form. Every complaint is recorded and handled confidentially.</p>
                        <h5 class="mb-3">What happens next</h5>
                        <ol class="ps-3 mb-4">
                            <li class="mb-2">You'll receive an email confirming we have your complaint, with a reference number.</li>
                            <li class="mb-2">Your complaint is recorded in our complaints register and assigned to a member of our team.</li>
                            <li class="mb-2">We'll contact you to discuss it and let you know the outcome.</li>
                        </ol>
                        <p class="mb-0">Prefer to speak to someone? See our <a href="contact.html">contact details</a>.</p>
                    </div>
                    <div class="col-lg-7 wow fadeInRight" data-wow-delay="0.3s">
                        <div class="bg-white rounded p-4 p-md-5 shadow-sm">
                            <form id="complaintForm" novalidate>
                                <div class="row g-3">
                                    <div class="col-12">
                                        <div class="form-floating">
                                            <input type="text" class="form-control" id="client_name" name="client_name" placeholder="Full name" maxlength="150" autocomplete="name" required>
                                            <label for="client_name">Full name *</label>
                                            <div class="invalid-feedback">Please enter your full name.</div>
                                        </div>
                                    </div>
                                    <div class="col-md-6">
                                        <div class="form-floating">
                                            <input type="tel" class="form-control" id="phone_number" name="phone_number" placeholder="Phone number" maxlength="40" pattern="[0-9+()\s.\-]{7,40}" autocomplete="tel" required>
                                            <label for="phone_number">Phone number *</label>
                                            <div class="invalid-feedback">Please enter a valid phone number.</div>
                                        </div>
                                    </div>
                                    <div class="col-md-6">
                                        <div class="form-floating">
                                            <input type="email" class="form-control" id="email_address" name="email_address" placeholder="Email address" maxlength="254" autocomplete="email" required>
                                            <label for="email_address">Email address *</label>
                                            <div class="invalid-feedback">Please enter a valid email address.</div>
                                        </div>
                                    </div>
                                    <div class="col-12">
                                        <div class="form-floating">
                                            <textarea class="form-control" id="nature_of_complaint" name="nature_of_complaint" placeholder="Nature of the complaint" style="height: 180px" minlength="10" maxlength="5000" required></textarea>
                                            <label for="nature_of_complaint">Nature of the complaint *</label>
                                            <div class="invalid-feedback">Please describe your complaint (at least 10 characters).</div>
                                        </div>
                                        <div class="form-text">Please include dates, account details and anything else that will help us look into it.</div>
                                    </div>
                                    <div class="col-12">
                                        <div class="form-floating">
                                            <input type="text" class="form-control" id="staff_member_involved" name="staff_member_involved" placeholder="Staff member involved" maxlength="150">
                                            <label for="staff_member_involved">Staff member involved (if any)</label>
                                        </div>
                                    </div>
                                    <!-- Leave empty: catches spam bots -->
                                    <div style="position:absolute;left:-10000px;" aria-hidden="true">
                                        <label for="website">Website</label>
                                        <input type="text" id="website" name="website" tabindex="-1" autocomplete="off">
                                    </div>
                                    <div class="col-12">
                                        <div class="form-check">
                                            <input class="form-check-input" type="checkbox" value="yes" id="consent" name="consent" required>
                                            <label class="form-check-label" for="consent">I agree that MMC Capital may use the details I've provided to investigate and respond to my complaint. *</label>
                                            <div class="invalid-feedback">Please tick this box so we can handle your complaint.</div>
                                        </div>
                                    </div>
                                    <div class="col-12">
                                        <div id="complaintAlert" class="alert alert-danger d-none mb-0" role="alert"></div>
                                    </div>
                                    <div class="col-12">
                                        <button id="complaintSubmit" class="btn btn-primary w-100 py-3" type="submit">Submit complaint</button>
                                    </div>
                                </div>
                            </form>
                            <div id="complaintSuccess" class="text-center py-4 d-none" tabindex="-1">
                                <i class="fa fa-check-circle text-primary mb-3" style="font-size: 3rem;" aria-hidden="true"></i>
                                <h3 class="mb-3">Thank you – we've received your complaint</h3>
                                <p class="mb-2" id="complaintRefLine">Your reference number is <strong id="complaintRef"></strong>.</p>
                                <p class="mb-0">We've sent a confirmation to your email address. A member of our team will be in touch.</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <script>
        (function () {
            var form = document.getElementById('complaintForm');
            var started = Date.now();
            var alertBox = document.getElementById('complaintAlert');
            var button = document.getElementById('complaintSubmit');

            function showError(message) {
                alertBox.textContent = message;
                alertBox.classList.remove('d-none');
            }

            form.addEventListener('submit', function (e) {
                e.preventDefault();
                alertBox.classList.add('d-none');
                form.querySelectorAll('.is-invalid').forEach(function (el) { el.classList.remove('is-invalid'); });
                if (!form.checkValidity()) {
                    form.classList.add('was-validated');
                    return;
                }
                var data = new FormData(form);
                data.append('form_started', String(started));
                button.disabled = true;
                button.textContent = 'Submitting…';

                fetch('submit-complaint.php', { method: 'POST', body: data })
                    .then(function (r) { return r.json().catch(function () { return { ok: false }; }); })
                    .then(function (res) {
                        if (res.ok) {
                            form.classList.add('d-none');
                            var success = document.getElementById('complaintSuccess');
                            if (res.reference) {
                                document.getElementById('complaintRef').textContent = res.reference;
                            } else {
                                document.getElementById('complaintRefLine').classList.add('d-none');
                            }
                            success.classList.remove('d-none');
                            success.focus();
                            return;
                        }
                        if (res.errors) {
                            Object.keys(res.errors).forEach(function (name) {
                                var el = form.elements[name];
                                if (el) { el.classList.add('is-invalid'); }
                            });
                        }
                        showError(res.message || 'Sorry, something went wrong. Please try again or contact us directly.');
                    })
                    .catch(function () {
                        showError('We could not send your complaint. Please check your internet connection and try again.');
                    })
                    .finally(function () {
                        button.disabled = false;
                        button.textContent = 'Submit complaint';
                    });
            });
        })();
        </script>
        <!-- Complaints End -->
HTML;

$title = 'Complaints - MMC Capital';
$description = 'Lodge a complaint with MMC Capital. Tell us about your experience and we will record, investigate and respond to it.';
$template = @file_get_contents(__DIR__ . '/contact.html');
$startMarker = '<!-- Header Start -->';
$endMarker = '<!-- Contact End -->';

if ($template !== false && ($start = strpos($template, $startMarker)) !== false && ($end = strpos($template, $endMarker)) !== false) {
    $page = substr($template, 0, $start) . trim($form) . substr($template, $end + strlen($endMarker));
    $page = preg_replace('~<title>.*?</title>~s', '<title>' . $title . '</title>', $page, 1);
    $page = preg_replace('~(<meta\s+(?:name="description"|property="og:description")\s+content=")[^"]*~', '${1}' . $description, $page);
    $page = preg_replace('~(<meta\s+property="og:title"\s+content=")[^"]*~', '${1}' . $title, $page);
    $page = preg_replace('~(<link\s+rel="canonical"\s+href="[^"]*?)contact(\.html)?(")~', '${1}complaints.php${3}', $page);
    $page = preg_replace('~(<meta\s+property="og:url"\s+content="[^"]*?)contact(\.html)?(")~', '${1}complaints.php${3}', $page);
    echo $page;
    exit;
}

// Fallback if contact.html is missing or its layout has changed.
?><!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?= htmlspecialchars($title) ?></title>
    <meta name="description" content="<?= htmlspecialchars($description) ?>">
    <link href="css/bootstrap.min.css" rel="stylesheet">
    <link href="css/style.css" rel="stylesheet">
</head>
<body>
<?= $form ?>
</body>
</html>
