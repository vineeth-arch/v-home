import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from vhome_companion.vnode import ssdp  # noqa: E402

LG = ("HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=1800\r\nLOCATION: http://192.168.29.225:3000/\r\n"
      "ST: urn:lge-com:service:webos-second-screen:1\r\nUSN: uuid:abc::urn:lge-com:service:webos-second-screen:1\r\n\r\n")


class ParseLocationTests(unittest.TestCase):
    def test_lg_response_gives_host(self):
        self.assertEqual(ssdp.parse_location(LG), "192.168.29.225")

    def test_header_names_are_case_insensitive_and_lf_only_works(self):
        self.assertEqual(ssdp.parse_location(LG.replace("\r\n", "\n").replace("LOCATION", "Location")),
                         "192.168.29.225")

    def test_usn_alone_is_enough(self):
        r = "HTTP/1.1 200 OK\r\nLOCATION: http://10.0.0.5:3000/\r\nUSN: uuid:x::urn:lge-com:service:webos-second-screen:1\r\n\r\n"
        self.assertEqual(ssdp.parse_location(r), "10.0.0.5")

    def test_other_devices_are_ignored(self):
        r = "HTTP/1.1 200 OK\r\nLOCATION: http://10.0.0.7:80/\r\nST: upnp:rootdevice\r\n\r\n"
        self.assertIsNone(ssdp.parse_location(r))

    def test_missing_or_bad_location(self):
        self.assertIsNone(ssdp.parse_location("ST: urn:lge-com:service:webos-second-screen:1\r\n\r\n"))
        self.assertIsNone(ssdp.parse_location("ST: webos-second-screen\r\nLOCATION: nonsense\r\n\r\n"))
        self.assertIsNone(ssdp.parse_location(""))

    def test_ipv6_location(self):
        r = "ST: urn:lge-com:service:webos-second-screen:1\r\nLOCATION: http://[fe80::1]:3000/\r\n\r\n"
        self.assertEqual(ssdp.parse_location(r), "fe80::1")


if __name__ == "__main__":
    unittest.main()
