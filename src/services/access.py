"""Allow only explicitly configured TCP peers; never trust proxy headers."""
from ipaddress import IPv4Address, IPv6Address, ip_address

Address = IPv4Address | IPv6Address


def parse_address(value: str) -> Address:
    # Interface-scoped addresses and hostnames are not allowlist entries.
    if '%' in value:
        raise ValueError('Scoped IP addresses are not supported')
    address = ip_address(value)
    if isinstance(address, IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


class IPAllowlist:
    def __init__(self, value: str):
        entries = value.strip().split(',') if value.strip() else []
        try:
            self.addresses = frozenset(parse_address(entry.strip()) for entry in entries)
        except ValueError:
            # Do not echo arbitrary configuration content in startup logs.
            raise ValueError('QSV_ALLOWED_PROXY_IPS must be comma-separated individual IPv4/IPv6 addresses') from None

    def permits(self, peer: str | None) -> bool:
        if peer is None:
            return False
        try:
            return parse_address(peer) in self.addresses
        except ValueError:
            return False
