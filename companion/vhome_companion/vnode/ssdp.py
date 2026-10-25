"""webOS TV discovery over SSDP (port of the Android Discovery class)."""
import asyncio
import socket
from urllib.parse import urlparse

LG_SERVICE = "webos-second-screen"
GROUP = ("239.255.255.250", 1900)
M_SEARCH = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
            'MAN: "ssdp:discover"\r\nMX: 2\r\nST: urn:lge-com:service:webos-second-screen:1\r\n\r\n')


def parse_location(response):
    """Host from the LOCATION header, only for responses that name the LG second-screen service."""
    try:
        headers = {}
        for line in response.replace("\r\n", "\n").split("\n"):
            name, sep, value = line.partition(":")
            if sep and name.strip():
                headers[name.strip().lower()] = value.strip()
        if not any(LG_SERVICE in headers.get(h, "").lower() for h in ("st", "usn")):
            return None
        return urlparse(headers["location"]).hostname or None
    except (KeyError, ValueError):
        return None


class _Collector(asyncio.DatagramProtocol):
    def __init__(self):
        self.hosts = []

    def datagram_received(self, data, addr):
        host = parse_location(data.decode("utf-8", "replace"))
        if host and host not in self.hosts:
            self.hosts.append(host)


async def search(timeout=3.0):
    """Hosts that answered the M-SEARCH within `timeout` seconds (empty on any network problem)."""
    loop = asyncio.get_running_loop()
    collector = _Collector()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: collector, family=socket.AF_INET, local_addr=("0.0.0.0", 0))
    except OSError:
        return []
    try:
        transport.sendto(M_SEARCH.encode(), GROUP)
        await asyncio.sleep(timeout)
    except OSError:
        pass
    finally:
        transport.close()
    return list(collector.hosts)
