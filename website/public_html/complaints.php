<?php
// Complaints page. It reuses contact.html's header, navigation, footer and
// styling, so it always matches the rest of the site, and swaps in the form.
// Works with both the new site design (<main id="main">) and the older template.
declare(strict_types=1);

// Shared behaviour for both designs.
$script = <<<'HTML'
<script>
(function () {
    var form = document.getElementById('complaintForm');
    if (!form) { return; }
    var started = Date.now();
    var alertBox = document.getElementById('complaintAlert');
    var button = document.getElementById('complaintSubmit');
    var label = button.textContent;

    function show(el) { el.hidden = false; el.style.display = ''; el.classList.remove('d-none'); }
    function hide(el) { el.hidden = true; el.style.display = 'none'; el.classList.add('d-none'); }
    function setError(el, message) {
        el.classList.add('is-invalid');
        el.setAttribute('aria-invalid', 'true');
        var err = document.getElementById(el.name + '-err');
        if (err) { err.textContent = message; }
    }
    function clearErrors() {
        form.querySelectorAll('[aria-invalid]').forEach(function (el) {
            el.classList.remove('is-invalid');
            el.removeAttribute('aria-invalid');
        });
        form.querySelectorAll('[id$="-err"]').forEach(function (el) { el.textContent = ''; });
        hide(alertBox);
    }
    function showMessage(message) {
        alertBox.textContent = message;
        show(alertBox);
        alertBox.focus();
    }

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        clearErrors();
        var firstBad = null;
        Array.prototype.forEach.call(form.elements, function (el) {
            if (el.name && el.willValidate && !el.checkValidity()) {
                setError(el, el.getAttribute('data-msg') || el.validationMessage);
                firstBad = firstBad || el;
            }
        });
        if (firstBad) { firstBad.focus(); return; }

        var data = new FormData(form);
        data.append('form_started', String(started));
        button.disabled = true;
        button.textContent = 'Submitting…';

        fetch('submit-complaint.php', { method: 'POST', body: data })
            .then(function (r) { return r.json().catch(function () { return { ok: false }; }); })
            .then(function (res) {
                if (res.ok) {
                    hide(form);
                    var success = document.getElementById('complaintSuccess');
                    if (res.reference) {
                        document.getElementById('complaintRef').textContent = res.reference;
                    } else {
                        hide(document.getElementById('complaintRefLine'));
                    }
                    show(success);
                    success.focus();
                    return;
                }
                if (res.errors) {
                    Object.keys(res.errors).forEach(function (name) {
                        var el = form.elements[name];
                        if (el) { setError(el, res.errors[name]); }
                    });
                }
                showMessage(res.message || 'Sorry, something went wrong. Please try again or contact us directly.');
            })
            .catch(function () {
                showMessage('We could not send your complaint. Please check your internet connection and try again.');
            })
            .finally(function () {
                button.disabled = false;
                button.textContent = label;
            });
    });
})();
</script>
HTML;

// New site design (assets/css/site.css).
$modern = <<<'HTML'
<main id="main">
    <section class="hero hero--page">
        <div class="hero__media"><img src="img/building-3.webp" alt="" fetchpriority="high"></div>
        <div class="wrap">
            <nav class="crumbs" aria-label="Breadcrumb"><a href="index.html">Home</a> &nbsp;/&nbsp; <a href="contact.html">Contact</a> &nbsp;/&nbsp; Complaints</nav>
            <p class="eyebrow">Complaints</p>
            <h1>We want to hear from you.</h1>
            <p class="lede">If you are unhappy with any service you have received from MMC Capital, or with the conduct of any of our staff, please tell us. Every complaint is recorded and handled confidentially.</p>
        </div>
    </section>
    <section class="section">
        <div class="wrap split split--47">
            <div class="reveal">
                <p class="eyebrow">What happens next</p><h2 style="font-size:var(--step-3)">How we handle your complaint</h2>
                <ul class="contact-list">
                    <li><span class="k">1. Acknowledgement</span>You'll receive an email confirming we have your complaint, with a reference number.</li>
                    <li><span class="k">2. Review</span>Your complaint is recorded in our complaints register and assigned to a member of our team.</li>
                    <li><span class="k">3. Outcome</span>We'll contact you to discuss it and let you know the outcome.</li>
                    <li><span class="k">Prefer to talk?</span><a href="contact.html">See our contact details</a></li>
                </ul>
            </div>
            <div class="reveal">
                <p class="eyebrow">Complaint form</p><h2 style="font-size:var(--step-3)">Lodge a complaint</h2>
                <form class="form" id="complaintForm" novalidate>
                    <div class="hp" aria-hidden="true"><label for="complaint-web">Website</label><input id="complaint-web" name="website" tabindex="-1" autocomplete="off"></div>
                    <div class="field full"><label for="client_name">Full name *</label><input id="client_name" name="client_name" autocomplete="name" required maxlength="150" data-msg="Please enter your full name."><span class="err" id="client_name-err" aria-live="polite"></span></div>
                    <div class="field"><label for="phone_number">Phone number *</label><input id="phone_number" name="phone_number" type="tel" autocomplete="tel" required maxlength="40" pattern="[0-9+()\s.\-]{7,40}" data-msg="Please enter a valid phone number."><span class="err" id="phone_number-err" aria-live="polite"></span></div>
                    <div class="field"><label for="email_address">Email *</label><input id="email_address" name="email_address" type="email" autocomplete="email" required maxlength="254" data-msg="Please enter a valid email address."><span class="err" id="email_address-err" aria-live="polite"></span></div>
                    <div class="field full"><label for="nature_of_complaint">Nature of the complaint *</label><textarea id="nature_of_complaint" name="nature_of_complaint" required minlength="10" maxlength="5000" data-msg="Please describe your complaint (at least 10 characters)." placeholder="Please include dates, account details and anything else that will help us look into it."></textarea><span class="err" id="nature_of_complaint-err" aria-live="polite"></span></div>
                    <div class="field full"><label for="staff_member_involved">Staff member involved (if any)</label><input id="staff_member_involved" name="staff_member_involved" maxlength="150"><span class="err" id="staff_member_involved-err" aria-live="polite"></span></div>
                    <div class="full consent"><input type="checkbox" id="consent" name="consent" value="yes" required data-msg="Please tick this box so we can handle your complaint."><label for="consent">I agree that MMC Capital may use the details I've provided to investigate and respond to my complaint. *</label></div>
                    <span class="err full" id="consent-err" aria-live="polite" style="color:var(--err);font-size:.82rem"></span>
                    <div class="full">
                        <button class="btn" id="complaintSubmit" type="submit">Submit complaint</button>
                        <div class="form-status" id="complaintAlert" role="alert" tabindex="-1" hidden></div>
                    </div>
                </form>
                <div id="complaintSuccess" tabindex="-1" hidden>
                    <h3>Thank you – we've received your complaint.</h3>
                    <p id="complaintRefLine">Your reference number is <strong id="complaintRef"></strong>.</p>
                    <p class="muted">We've sent a confirmation to your email address. A member of our team will be in touch.</p>
                </div>
            </div>
        </div>
    </section>
</main>
HTML;

// Older Bootstrap template (css/style.css).
$legacy = <<<'HTML'
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
                                    <div class="col-12"><div class="form-floating">
                                        <input type="text" class="form-control" id="client_name" name="client_name" placeholder="Full name" maxlength="150" autocomplete="name" required data-msg="Please enter your full name.">
                                        <label for="client_name">Full name *</label>
                                        <div class="invalid-feedback" id="client_name-err"></div>
                                    </div></div>
                                    <div class="col-md-6"><div class="form-floating">
                                        <input type="tel" class="form-control" id="phone_number" name="phone_number" placeholder="Phone number" maxlength="40" pattern="[0-9+()\s.\-]{7,40}" autocomplete="tel" required data-msg="Please enter a valid phone number.">
                                        <label for="phone_number">Phone number *</label>
                                        <div class="invalid-feedback" id="phone_number-err"></div>
                                    </div></div>
                                    <div class="col-md-6"><div class="form-floating">
                                        <input type="email" class="form-control" id="email_address" name="email_address" placeholder="Email address" maxlength="254" autocomplete="email" required data-msg="Please enter a valid email address.">
                                        <label for="email_address">Email address *</label>
                                        <div class="invalid-feedback" id="email_address-err"></div>
                                    </div></div>
                                    <div class="col-12">
                                        <div class="form-floating">
                                            <textarea class="form-control" id="nature_of_complaint" name="nature_of_complaint" placeholder="Nature of the complaint" style="height: 180px" minlength="10" maxlength="5000" required data-msg="Please describe your complaint (at least 10 characters)."></textarea>
                                            <label for="nature_of_complaint">Nature of the complaint *</label>
                                            <div class="invalid-feedback" id="nature_of_complaint-err"></div>
                                        </div>
                                        <div class="form-text">Please include dates, account details and anything else that will help us look into it.</div>
                                    </div>
                                    <div class="col-12"><div class="form-floating">
                                        <input type="text" class="form-control" id="staff_member_involved" name="staff_member_involved" placeholder="Staff member involved" maxlength="150">
                                        <label for="staff_member_involved">Staff member involved (if any)</label>
                                        <div class="invalid-feedback" id="staff_member_involved-err"></div>
                                    </div></div>
                                    <div style="position:absolute;left:-10000px;" aria-hidden="true">
                                        <label for="website">Website</label>
                                        <input type="text" id="website" name="website" tabindex="-1" autocomplete="off">
                                    </div>
                                    <div class="col-12"><div class="form-check">
                                        <input class="form-check-input" type="checkbox" value="yes" id="consent" name="consent" required data-msg="Please tick this box so we can handle your complaint.">
                                        <label class="form-check-label" for="consent">I agree that MMC Capital may use the details I've provided to investigate and respond to my complaint. *</label>
                                        <div class="invalid-feedback" id="consent-err"></div>
                                    </div></div>
                                    <div class="col-12"><div id="complaintAlert" class="alert alert-danger d-none mb-0" role="alert" tabindex="-1"></div></div>
                                    <div class="col-12"><button id="complaintSubmit" class="btn btn-primary w-100 py-3" type="submit">Submit complaint</button></div>
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
        <!-- Complaints End -->
HTML;

$title = 'Complaints - MMC Capital';
$description = 'Lodge a complaint with MMC Capital. Tell us about your experience and we will record, investigate and respond to it.';

function mmc_page_meta(string $page, string $title, string $description): string
{
    $page = preg_replace('~<title>.*?</title>~s', '<title>' . $title . '</title>', $page, 1);
    $page = preg_replace('~(<meta\s+(?:name="description"|property="og:description")\s+content=")[^"]*~', '${1}' . $description, $page);
    $page = preg_replace('~(<meta\s+property="og:title"\s+content=")[^"]*~', '${1}' . $title, $page);
    $page = preg_replace('~(<link\s+rel="canonical"\s+href="[^"]*?)contact(\.html)?(")~', '${1}complaints.php${3}', $page);
    $page = preg_replace('~(<meta\s+property="og:url"\s+content="[^"]*?)contact(\.html)?(")~', '${1}complaints.php${3}', $page);
    return $page;
}

$template = @file_get_contents(__DIR__ . '/contact.html');
$page = null;

if ($template !== false) {
    $mainStart = strpos($template, '<main id="main">');
    $mainEnd = strpos($template, '</main>');
    $oldStart = strpos($template, '<!-- Header Start -->');
    $oldEnd = strpos($template, '<!-- Contact End -->');

    if ($mainStart !== false && $mainEnd !== false && $mainEnd > $mainStart) {
        $page = substr($template, 0, $mainStart) . $modern . "\n" . $script . substr($template, $mainEnd + strlen('</main>'));
    } elseif ($oldStart !== false && $oldEnd !== false && $oldEnd > $oldStart) {
        $page = substr($template, 0, $oldStart) . trim($legacy) . "\n" . $script . substr($template, $oldEnd + strlen('<!-- Contact End -->'));
    }
}

if ($page !== null) {
    echo mmc_page_meta($page, $title, $description);
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
    <link href="assets/css/site.css" rel="stylesheet">
</head>
<body>
<?= $modern ?>
<?= $script ?>
</body>
</html>
