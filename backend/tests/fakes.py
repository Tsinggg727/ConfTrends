"""测试替身。

FakeFetcher 实现与 crawl.fetcher.Fetcher 相同的三个方法（get / get_list /
get_detail），但返回预置的 HTML —— 用例因此不依赖网络，也就不会因为
站点改版或限流而红。
"""
from crawl.fail_reason import CrawlError


class FakeFetcher:
    """按 URL 派发预置内容，并记录调用顺序。"""

    def __init__(self, pages=None, errors=None):
        self.pages = dict(pages or {})      # url -> html
        self.errors = dict(errors or {})    # url -> CrawlError
        self.calls = []                     # [(url, kind)]，按发生顺序

    def get(self, url, kind="detail"):
        self.calls.append((url, kind))
        if url in self.errors:
            raise self.errors[url]
        if url not in self.pages:
            # 测试里出现没预置的 URL 一定是用例写错了，直接暴露出来
            raise AssertionError(f"FakeFetcher 没有预置 {url}")
        return self.pages[url]

    def get_list(self, url):
        return self.get(url, "list")

    def get_detail(self, url):
        return self.get(url, "detail")

    def stats(self):
        return {"requests": len(self.calls), "retries": 0, "blocked": 0,
                "blocked_hosts": []}

    # 便利方法
    def urls(self):
        return [u for u, _ in self.calls]

    def kinds(self):
        return [k for _, k in self.calls]
