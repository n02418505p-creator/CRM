"""Reads the extra detail out of website enquiries.

The Advisory and Stockbroker 'Request this service' forms send messages like:

    subject: [Advisory service request] Capital Raising
    message: Service: Capital Raising
             Organisation: Acme Ltd
             Telephone: +263 77 ...
             Page: /advisory-services.html

             <what the client wrote>

             Consent to be contacted: yes

The Contact Us form sends 'enquiry_about' as "<division>|<topic>", e.g. "advisory|Capital Raising".
"""
import re

SERVICE_SUBJECT = re.compile(r"^\[(Advisory|Stockbroking) service request\]\s*(.*)$", re.IGNORECASE)
HEADER_LINE = re.compile(r"^(Service|Organisation|Telephone|Page):\s*(.*)$")
HEADER_FIELDS = {"Service": "service", "Organisation": "organisation", "Telephone": "phone_number", "Page": "source_page"}
DIVISIONS = {"advisory", "stockbroking", "general"}


def parse(subject="", message="", enquiry_about=""):
    """Return a dict of any of: enquiry_type, division, service, organisation,
    phone_number, source_page, subject, message (cleaned)."""
    info = {}
    subject = (subject or "").strip()
    m = SERVICE_SUBJECT.match(subject)
    if m:
        info["division"] = "advisory" if m.group(1).lower() == "advisory" else "stockbroking"
        info["service"] = m.group(2).strip()

    lines = (message or "").replace("\r\n", "\n").split("\n")
    i, found = 0, False
    while i < len(lines) and HEADER_LINE.match(lines[i].strip()):
        key, value = HEADER_LINE.match(lines[i].strip()).groups()
        value = value.strip()
        if value and value != "-" and not info.get(HEADER_FIELDS[key]):
            info[HEADER_FIELDS[key]] = value
        found, i = True, i + 1
    if found:
        body = "\n".join(lines[i:]).strip()
        info["message"] = re.sub(r"\n*Consent to be contacted:\s*yes\s*$", "", body, flags=re.IGNORECASE).strip()

    if enquiry_about and "|" in enquiry_about:
        division, topic = enquiry_about.split("|", 1)
        division = division.strip().lower()
        if division in DIVISIONS:
            info.setdefault("division", division)
        if topic.strip():
            info.setdefault("service", topic.strip()[:120])

    service = info.get("service", "")
    if service:
        general = service.lower() in ("general enquiry", "general") or info.get("division") == "general"
        info["enquiry_type"] = "general" if general else "service"
        if m and not general:
            info["subject"] = f"Service request: {service}"
    elif subject:
        info["enquiry_type"] = "general"
    return info


# Services offered, as described on the website's service pages.
SERVICES = {
    "advisory": [
        ("Transaction Advisory", "We provide end-to-end support for complex corporate transactions, ensuring deal success and maximum value for our clients."),
        ("Capital Raising", "We structure and facilitate bespoke financing solutions to fuel growth and strategic initiatives. Our deal flow includes major capital raises for listed entities on the ZSE and VFEX. We assist clients in raising capital through various channels, including private placements, public offerings, and debt financing. Our team leverages extensive networks and market knowledge to connect clients with potential investors and secure optimal funding solutions."),
        ("Strategic Advisory", "We work closely with executive leadership to define, structure, and execute long-term corporate strategy."),
    ],
    "stockbroking": [
        ("Securities Trading", "We provide trade execution to both local and international clients. Our experienced stockbrokers are guided by the principle of fair execution of orders, ensuring clients' best interests are served. We help clients build balanced equities portfolios designed for long-term growth through expert advisory and best execution in secondary markets."),
        ("Custodial Services", "We offer broker controlled custodial services that allow our clients to trade electronically all listed equities and the service is underwritten by reputable commercial banks and the Zimbabwe Stock Exchange."),
        ("Advisory & Sponsoring Broker Services", "Strategic guidance for complex financial transactions and portfolio management. Our advisory team provides expert counsel on market strategies and corporate actions."),
        ("Research Services", "MMC Stockbrokers provides comprehensive research solutions and information management requirements for its clients, delivering actionable insights and market intelligence."),
        ("Direct Market Access", "Our clients have direct access to ZSE, FINSEC, VFEX and such other exchanges that might be introduced from time through ZSE Direct trading platforms."),
        ("Opening a trading account", ""),
    ],
    "general": [
        ("General enquiry", ""),
        ("Research distribution list", ""),
        ("Media enquiry", ""),
    ],
}
DIVISION_LABELS = {"advisory": "MMC Capital Advisory", "stockbroking": "MMC Stockbrokers", "general": "Other"}
_LOOKUP = {name.lower(): (division, name, desc) for division, items in SERVICES.items() for name, desc in items}


def service_info(name):
    """(division, canonical name, description) for a service name, or None."""
    return _LOOKUP.get((name or "").strip().lower())


def service_choices():
    """Grouped choices for a <select>."""
    return [("", "Choose…")] + [
        (DIVISION_LABELS[division], [(name, name) for name, _ in items]) for division, items in SERVICES.items()
    ]
