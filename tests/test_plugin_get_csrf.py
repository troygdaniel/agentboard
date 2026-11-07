"""A plugin's GET route is refused when the browser says the request came from another site (sec2-plugin-get-csrf, Nov 7): the Host is
the real one and a simple GET carries no Origin, so an <img> or a no-cors fetch on a hostile page reached /api/x/<plugin>/<route>. Nothing
in the home plugin does anything on a GET today; this is the net for the next plugin. Assets (page.js) are not routes and stay as they were."""
import unittest

from test_plugins import WithAPlugin


class PluginGetCsrfTests(WithAPlugin):
    def test_a_cross_site_get_is_refused_before_the_plugin_runs(self):
        for site in ("cross-site", "same-site", "Cross-Site "):
            code, out = self.call("/api/x/demo/hello?name=troy", headers={"Sec-Fetch-Site": site})
            self.assertEqual((code, out), (403, {"error": "bad origin"}), site)
        for hdr in ({"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "image"},   # an <img>
                    {"Origin": "http://evil.com"}):                                                                 # an old browser's cross-site fetch
            self.assertEqual(self.call("/api/x/demo/hello?name=troy", headers=hdr)[0], 403, hdr)

    def test_the_page_curl_and_a_typed_address_still_get_the_route(self):
        for hdr in ({"Sec-Fetch-Site": "same-origin"}, {"Sec-Fetch-Site": "none"}, {}):
            code, out = self.call("/api/x/demo/hello?name=troy", headers=hdr)
            self.assertEqual(code, 200, hdr)
            self.assertEqual(out["hi"], "troy")

    def test_the_page_script_is_an_asset_not_a_route(self):
        self.assertEqual(self.call("/api/x/demo/page.js", headers={"Sec-Fetch-Site": "cross-site"}, raw=True)[0], 200)

    def test_an_unknown_route_is_still_a_404_whatever_the_header(self):
        self.assertEqual(self.call("/api/x/demo/nothing", headers={"Sec-Fetch-Site": "cross-site"})[0], 404)


if __name__ == "__main__":
    unittest.main()
