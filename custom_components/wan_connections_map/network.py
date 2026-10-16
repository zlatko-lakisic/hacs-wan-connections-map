"""Turn an ASN organization into a short network label."""

from __future__ import annotations

_RESIDENTIAL_FIRST = (
    "google fiber",
    "google wifi",
    "google fi",
)

_SERVICES = (
    ("netflix", "Netflix"),
    ("amazon", "Amazon Web Services"),
    ("cloudfront", "Amazon Web Services"),
    ("google", "Google"),
    ("cloudflare", "Cloudflare"),
    ("akamai", "Akamai"),
    ("linode", "Akamai"),
    ("fastly", "Fastly"),
    ("azure", "Azure"),
    ("microsoft", "Microsoft"),
    ("apple", "Apple"),
    ("icloud", "Apple"),
    ("facebook", "Meta"),
    ("meta platforms", "Meta"),
    ("instagram", "Meta"),
    ("whatsapp", "Meta"),
    ("digitalocean", "DigitalOcean"),
    ("hetzner", "Hetzner"),
    ("ovh", "OVH"),
    ("contabo", "Contabo"),
    ("vultr", "Vultr"),
    ("choopa", "Vultr"),
    ("leaseweb", "Leaseweb"),
    ("oracle", "Oracle"),
    ("github", "GitHub"),
    ("discord", "Discord"),
    ("spotify", "Spotify"),
    ("twitch", "Twitch"),
    ("hulu", "Hulu"),
    ("disney", "Disney"),
    ("hbo", "Max"),
    ("steam", "Steam"),
    ("valve", "Steam"),
    ("epic games", "Epic Games"),
    ("riot games", "Riot"),
    ("blizzard", "Blizzard"),
    ("nintendo", "Nintendo"),
    ("playstation", "PlayStation"),
    ("zoom", "Zoom"),
    ("slack", "Slack"),
    ("dropbox", "Dropbox"),
    ("alibaba", "Alibaba"),
    ("tencent", "Tencent"),
    ("huawei cloud", "Huawei Cloud"),
    ("ibm", "IBM"),
    ("softlayer", "IBM"),
    ("scaleway", "Scaleway"),
    ("online s.a.s", "Scaleway"),
    ("m247", "M247"),
    ("datacamp", "Datacamp"),
    ("cdn77", "CDN77"),
    ("stackpath", "StackPath"),
    ("edgecast", "Edgio"),
    ("quadranet", "QuadraNet"),
)

_RESIDENTIAL = (
    "comcast",
    "xfinity",
    "charter",
    "spectrum",
    "cox comm",
    "verizon",
    "at&t",
    "att enterprises",
    "centurylink",
    "lumen",
    "frontier",
    "windstream",
    "optimum",
    "altice",
    "mediacom",
    "suddenlink",
    "sparklight",
    "cable one",
    "astound",
    "breezeline",
    "rcn ",
    "t-mobile",
    "tmobile",
    "rogers",
    "bell canada",
    "telus",
    "shaw communications",
    "videotron",
    "cogeco",
    "sasktel",
    "british telecom",
    "talktalk",
    "virgin media",
    "vodafone",
    "deutsche telekom",
    "telefonica",
    "orange s.a",
    "proximus",
    "ziggo",
    "kpn ",
    "telia",
    "telenor",
    "swisscom",
    "telecom italia",
    "fastweb",
    "bouygues",
    "optus",
    "telstra",
    "iinet",
    "softbank",
    "kddi",
    "bh telecom",
    "logosoft",
    "telemach",
    "mtel",
    "hrvatski telekom",
    "a1 telekom",
    "a1 hrvatska",
    "a1 slovenija",
)

_ISP_HINTS = (
    "telecom",
    "telekom",
    "broadband",
    "cable",
    "communications",
    "wireless",
    "mobile",
    "fibre",
    "fiber",
    "dsl",
    "isp",
)

_HOSTING = (
    "hosting",
    "datacenter",
    "data center",
    "data centre",
    "colocation",
    "colo ",
    "server",
    "cloud",
    "vps",
    "dedicated",
)


def classify(org: str, *, incoming: bool) -> str:
    """Label a peer from its ASN organization."""
    text = " ".join(str(org or "").lower().split())
    if not text:
        return ""
    if _matches(text, _RESIDENTIAL_FIRST) or _matches(text, _RESIDENTIAL):
        return "Residential"
    service = _service(text)
    if service:
        if incoming:
            return f"Server farm · {service}"
        return service
    if _matches(text, _HOSTING):
        name = " ".join(str(org).split())
        if incoming:
            return f"Server farm · {name}"
        return name
    if _matches(text, _ISP_HINTS):
        return "Residential"
    name = " ".join(str(org).split())
    return name


def _service(text: str) -> str:
    for needle, label in _SERVICES:
        if needle in text:
            return label
    return ""


def _matches(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
