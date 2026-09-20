"""限速器测试 —— 验证设计文档 §1.3 的四条合规约束真的落地了。

用桩 Session 替掉 requests，所以不联网也能验证「间隔、并发、UA、遇 429 停手」。
"""
import threading
import time

import pytest

from crawl.fail_reason import CrawlError
from crawl.fetcher import Fetcher

UA = "ConfTrends-test/0.1 (course project; contact: student@example.edu)"


class StubResponse:
    def __init__(self, status=200, text="<html>ok</html>", headers=None):
        self.status_code = status
        self.text = text
        self.content = text.encode("utf-8")
        self.encoding = "utf-8"
        self.headers = headers or {}


class StubSession:
    """按 URL 顺序派发预置响应，并记录调用时刻。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []            # [(url, 时刻)]

    def get(self, url, timeout=None):
        self.calls.append((url, time.monotonic()))
        if url.endswith("/robots.txt"):
            return StubResponse(404, "not found")
        return self.responses.pop(0) if self.responses else StubResponse()


class StubFetcher(Fetcher):
    """把 _session() 换掉，而不是往线程局部变量里塞 ——
    Fetcher 每线程一个 Session，只替换当前线程的话，工作线程会去真的联网。"""

    def __init__(self, session, **kwargs):
        kwargs.setdefault("user_agent", UA)
        kwargs.setdefault("respect_robots", False)
        kwargs.setdefault("min_interval", 0.0)
        kwargs.setdefault("max_interval", 0.0)
        super().__init__(**kwargs)
        self.stub = session

    def _session(self):
        return self.stub


def make_fetcher(responses, **kwargs):
    return StubFetcher(StubSession(responses), **kwargs)


# ---------------------------------------------------------------
# 约束 1：请求间隔 0.5–1.0s
# ---------------------------------------------------------------
def test_请求间隔不低于下限():
    session = StubSession([StubResponse() for _ in range(3)])
    f = StubFetcher(session, min_interval=0.2, max_interval=0.25)

    for _ in range(3):
        f.get_detail("https://example.com/a")

    stamps = [t for _, t in session.calls]
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert len(gaps) == 2
    assert all(g >= 0.19 for g in gaps), f"间隔不足：{gaps}"


def test_第一次请求不等待():
    f = StubFetcher(StubSession([StubResponse()]),
                    min_interval=5.0, max_interval=5.0)
    t0 = time.monotonic()
    f.get_detail("https://example.com/a")
    assert time.monotonic() - t0 < 1.0        # 不该为第一次请求白等 5 秒


def test_默认参数就是设计要求的值():
    f = Fetcher(user_agent=UA)
    assert (f.min_interval, f.max_interval) == (0.5, 1.0)
    assert f.max_retries == 2
    assert f.list_timeout >= 30 and f.detail_timeout >= 15


# ---------------------------------------------------------------
# 并发上限
# ---------------------------------------------------------------
def test_并发不超过上限():
    peak = {"now": 0, "max": 0}
    lock = threading.Lock()

    class SlowSession(StubSession):
        def get(self, url, timeout=None):
            with lock:
                peak["now"] += 1
                peak["max"] = max(peak["max"], peak["now"])
            time.sleep(0.05)
            with lock:
                peak["now"] -= 1
            return StubResponse()

    f = StubFetcher(SlowSession([]), concurrency=2)

    def worker():
        f.get_detail("https://example.com/a")

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak["max"] <= 2, f"并发达到 {peak['max']}，超过上限 2"
    assert peak["max"] > 1, "并发从未超过 1，用例没有真正验证并发上限"


# ---------------------------------------------------------------
# 约束 3：标识性 UA
# ---------------------------------------------------------------
def test_user_agent带项目标识与联系方式():
    f = Fetcher(user_agent=UA)
    assert "ConfTrends" in f.headers["User-Agent"]
    assert "contact" in f.headers["User-Agent"]
    assert "Mozilla" not in f.headers["User-Agent"]     # 不伪装浏览器


# ---------------------------------------------------------------
# 约束 4：遇 403 / 429 停手
# ---------------------------------------------------------------
def test_429立即停手并熔断():
    f = make_fetcher([StubResponse(429)])
    with pytest.raises(CrawlError) as exc:
        f.get_detail("https://example.com/a")
    assert exc.value.code == "PAGE_FETCH_FAILED"
    assert "暂停" in exc.value.message

    # 熔断期间不再发起请求 —— 这是「不硬闯」的关键
    before = len(f.stub.calls)
    with pytest.raises(CrawlError) as exc2:
        f.get_detail("https://example.com/b")
    assert "暂停期" in exc2.value.message
    assert len(f.stub.calls) == before
    assert f.stats()["blocked_hosts"] == ["example.com"]


def test_403同样熔断():
    f = make_fetcher([StubResponse(403)])
    with pytest.raises(CrawlError):
        f.get_detail("https://example.com/a")
    assert f.stats()["blocked"] == 1


def test_熔断只影响出问题的站点():
    f = make_fetcher([StubResponse(429), StubResponse(200)])
    with pytest.raises(CrawlError):
        f.get_detail("https://bad.example.com/a")
    assert f.get_detail("https://good.example.com/a") == "<html>ok</html>"


# ---------------------------------------------------------------
# 重试与不退让的错误
# ---------------------------------------------------------------
def test_5xx重试后成功():
    f = make_fetcher([StubResponse(503), StubResponse(500), StubResponse(200)],
                     backoff_base=0.01)
    assert f.get_detail("https://example.com/a") == "<html>ok</html>"
    assert f.stats()["retries"] == 2
    assert f.stats()["requests"] == 3


def test_重试用尽后抛错():
    f = make_fetcher([StubResponse(500) for _ in range(5)], backoff_base=0.01)
    with pytest.raises(CrawlError) as exc:
        f.get_detail("https://example.com/a")
    assert exc.value.code == "PAGE_FETCH_FAILED"


def test_404不重试():
    f = make_fetcher([StubResponse(404)])
    with pytest.raises(CrawlError):
        f.get_detail("https://example.com/a")
    assert len(f.stub.calls) == 1


def test_网络异常重试后仍失败记为网络错误():
    import requests

    class BrokenSession(StubSession):
        def get(self, url, timeout=None):
            self.calls.append((url, time.monotonic()))
            raise requests.ConnectionError("boom")

    f = StubFetcher(BrokenSession([]), backoff_base=0.01)
    with pytest.raises(CrawlError) as exc:
        f.get_detail("https://example.com/a")
    assert exc.value.code == "NETWORK_ERROR"
    assert len(f.stub.calls) == 3          # 初次 + 2 次重试


def test_列表页超时比详情页宽松():
    f = Fetcher(user_agent=UA)
    assert f.list_timeout > f.detail_timeout


# ---------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------
def test_robots禁止时不发请求():
    class RobotsSession(StubSession):
        def get(self, url, timeout=None):
            self.calls.append((url, time.monotonic()))
            if url.endswith("/robots.txt"):
                return StubResponse(200, "User-agent: *\nDisallow: /\n")
            return StubResponse(200, "<html>should not reach</html>")

    f = StubFetcher(RobotsSession([]), respect_robots=True)
    with pytest.raises(CrawlError) as exc:
        f.get_detail("https://example.com/paper/1")
    assert "robots" in exc.value.message
    # 只请求了 robots.txt，目标页一次都没碰
    assert [u for u, _ in f.stub.calls] == ["https://example.com/robots.txt"]


def test_robots_404视为完全放行():
    """CVF 实测就是 404 —— 按 RFC 9309，4xx 表示没有限制。"""
    f = StubFetcher(StubSession([StubResponse(200, "<html>ok</html>")]),
                    respect_robots=True)
    assert f.get_detail("https://openaccess.thecvf.com/x") == "<html>ok</html>"


def test_robots只声明其他爬虫时我们仍可抓():
    """ECVA 实测只声明 Googlebot、没有 Disallow —— 对我们等于放行。"""
    class GoogleOnly(StubSession):
        def get(self, url, timeout=None):
            self.calls.append((url, time.monotonic()))
            if url.endswith("/robots.txt"):
                return StubResponse(200, "User-agent: Googlebot\nAllow: /\n")
            return StubResponse(200, "<html>ok</html>")

    f = StubFetcher(GoogleOnly([]), respect_robots=True)
    assert f.get_detail("https://www.ecva.net/papers.php") == "<html>ok</html>"


def test_robots结果被缓存不重复请求():
    f = StubFetcher(StubSession(
        [StubResponse(200, "<html>1</html>"), StubResponse(200, "<html>2</html>")]),
        respect_robots=True)
    f.get_detail("https://example.com/a")
    f.get_detail("https://example.com/b")
    robots_calls = [u for u, _ in f.stub.calls if u.endswith("robots.txt")]
    assert len(robots_calls) == 1
