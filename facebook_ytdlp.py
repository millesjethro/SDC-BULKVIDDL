"""Run yt-dlp with Facebook cookies supplied through standard input."""
from functools import cached_property
from http.cookiejar import Cookie
import json
import sys

import yt_dlp


class FacebookDownloader(yt_dlp.YoutubeDL):
    @cached_property
    def cookiejar(self):
        jar = super().cookiejar
        for name, value in self.facebook_session.items():
            jar.set_cookie(Cookie(
                version=0, name=name, value=value, port=None, port_specified=False,
                domain=".facebook.com", domain_specified=True, domain_initial_dot=True,
                path="/", path_specified=True, secure=True, expires=None, discard=True,
                comment=None, comment_url=None, rest={},
            ))
        return jar


if __name__ == "__main__":
    FacebookDownloader.facebook_session = json.load(sys.stdin)
    yt_dlp.YoutubeDL = FacebookDownloader
    yt_dlp.main()
