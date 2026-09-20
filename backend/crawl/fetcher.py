"""限速抓取器 —— 全站唯一的出网口。

设计文档 §1.3 的合规要求，在这里落成四条硬约束：

  1. **间隔 0.5–1.0s**：两次请求的「发起时刻」至少隔这么久（随机抖动），
     避免变成规律的机器脉冲。
  2. **并发 ≤ 2**：信号量兜住，防止以后加批量任务时把站点压垮。
  3. **标识性 User-Agent**：带项目名与联系方式，不伪装浏览器。
  4. **遇 403/429 立即停手**：熔断该站点一段时间，而不是硬闯。

另外遵守 robots.txt（实测 CVF 无 robots.txt，ECVA 只声明 Googlebot，
两边对我们都是放行的 —— 但代码不能靠「实测恰好放行」，得真的去读）。
"""
import random
import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from .fail_reason import CrawlError

# 站点拒绝服务时的熔断时长（秒）。宁可让用户看到「已暂停」，
# 也不要持续敲门把自己变成攻击流量。
DEFAULT_BLOCK_COOLDOWN = 300

# robots.txt 缓存时长
_ROBOTS_TTL = 3600


class Fetcher:
    """带限速、重试、熔断的 HTTP 客户端。

    线程安全：可以在批量任务的线程池里共用同一个实例，
    间隔与熔断是全局的 —— 这正是限速想要的语义。
    """

    def __init__(
        self,
        user_agent,
        min_interval=0.5,
        max_interval=1.0,
        concurrency=2,
        list_timeout=60,
        detail_timeout=30,
        max_retries=2,
        backoff_base=2.0,
        respect_robots=True,
        block_cooldown=DEFAULT_BLOCK_COOLDOWN,
    ):
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.max_interval = max(min_interval, max_interval)
        self.list_timeout = list_timeout
        self.detail_timeout = detail_timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.respect_robots = respect_robots
        self.block_cooldown = block_cooldown

        self.headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }

        self._local = threading.local()          # 每线程一个 Session
        self._sem = threading.Semaphore(concurrency)
        self._pace_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._next_allowed = 0.0                 # 下一次允许发起请求的时刻
        self._blocked = {}                       # host -> 熔断截止时刻
        self._robots = {}                        # host -> (抓取时刻, RobotFileParser|None)
        self._counters = {"requests": 0, "retries": 0, "blocked": 0}

    # -----------------------------------------------------------
    # 对外接口
    # -----------------------------------------------------------
    def get_list(self, url):
        """抓列表/索引页（5–7 MB，超时放宽到 60s）。"""
        return self.get(url, kind="list")

    def get_detail(self, url):
        """抓详情页（4–7 KB，30s 足够）。"""
        return self.get(url, kind="detail")

    def get(self, url, kind="detail"):
        """抓一个页面，返回解码后的 HTML 文本。

        失败一律抛 CrawlError，带 §1.2 的失败码，上层不需要认识 requests 的异常族。
        """
        host = urlparse(url).netloc
        self._check_breaker(host)

        if self.respect_robots and not self._robots_allows(url):
            raise CrawlError("PAGE_FETCH_FAILED", f"robots.txt 不允许抓取 {url}")

        timeout = self.list_timeout if kind == "list" else self.detail_timeout
        last_error = None

        with self._sem:                          # 约束 2：并发 ≤ 2
            for attempt in range(self.max_retries + 1):
                self._wait_turn()                # 约束 1：间隔 0.5–1s
                try:
                    resp = self._session().get(url, timeout=timeout)
                except requests.RequestException as exc:
                    last_error = CrawlError(
                        "NETWORK_ERROR",
                        f"请求失败：{type(exc).__name__}",
                        exc,
                    )
                    self._counters["retries"] += 1
                    self._sleep_backoff(attempt, None)
                    continue

                self._counters["requests"] += 1

                if resp.status_code == 200:
                    return self._decode(resp)

                if resp.status_code in (403, 429):
                    # 约束 4：站点明确表示不欢迎，停手
                    self._trip_breaker(host, resp.status_code)
                    raise CrawlError(
                        "PAGE_FETCH_FAILED",
                        f"站点返回 {resp.status_code}，已暂停抓取 {host} "
                        f"{self.block_cooldown // 60} 分钟",
                    )

                if resp.status_code >= 500:
                    last_error = CrawlError(
                        "PAGE_FETCH_FAILED", f"服务端错误 HTTP {resp.status_code}"
                    )
                    self._counters["retries"] += 1
                    self._sleep_backoff(attempt, resp)
                    continue

                # 404 等确定性错误：重试没有意义
                raise CrawlError("PAGE_FETCH_FAILED", f"HTTP {resp.status_code}")

        raise last_error or CrawlError("PAGE_FETCH_FAILED", "请求失败且未取得响应")

    def stats(self):
        with self._state_lock:
            data = dict(self._counters)
            now = time.monotonic()
            data["blocked_hosts"] = [h for h, t in self._blocked.items() if t > now]
        return data

    # -----------------------------------------------------------
    # 内部
    # -----------------------------------------------------------
    def _session(self):
        s = getattr(self._local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update(self.headers)
            self._local.session = s
        return s

    def _wait_turn(self):
        """排定本次请求的发起时刻。

        先在锁内**预约**一个时刻就立刻放锁，再在锁外 sleep ——
        这样并发 2 的时候两个请求能真正并行在途，只是发起时刻错开，
        而不是被限速器串成一条线。
        """
        with self._pace_lock:
            now = time.monotonic()
            start = max(now, self._next_allowed)
            self._next_allowed = start + random.uniform(self.min_interval, self.max_interval)
        delay = start - now
        if delay > 0:
            time.sleep(delay)

    def _sleep_backoff(self, attempt, resp):
        if attempt >= self.max_retries:
            return
        delay = self.backoff_base * (2 ** attempt)      # 2s → 4s → 8s
        if resp is not None:
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit():
                delay = min(60.0, max(delay, float(retry_after)))
        time.sleep(delay)

    def _check_breaker(self, host):
        with self._state_lock:
            until = self._blocked.get(host, 0)
        if until > time.monotonic():
            raise CrawlError(
                "PAGE_FETCH_FAILED",
                f"{host} 处于暂停期，剩余 {int(until - time.monotonic())} 秒",
            )

    def _trip_breaker(self, host, status):
        with self._state_lock:
            self._blocked[host] = time.monotonic() + self.block_cooldown
            self._counters["blocked"] += 1

    @staticmethod
    def _decode(resp):
        """按 UTF-8 解码。

        requests 对没声明编码的 HTML 会默认按 latin-1 解，作者名里的重音字符
        会变成乱码 —— 这类脏数据进了库很难回头清理，所以在源头堵住。
        """
        enc = (resp.encoding or "").lower()
        if not enc or enc in ("iso-8859-1", "latin-1"):
            enc = "utf-8"
        return resp.content.decode(enc, errors="replace")

    # -----------------------------------------------------------
    # robots.txt
    # -----------------------------------------------------------
    def _robots_allows(self, url):
        host = urlparse(url).netloc
        parser = self._robots_for(host)
        if parser is None:
            return True                          # 拿不到 robots.txt 视为放行
        return parser.can_fetch(self.user_agent, url)

    def _robots_for(self, host):
        with self._state_lock:
            cached = self._robots.get(host)
        if cached and time.monotonic() - cached[0] < _ROBOTS_TTL:
            return cached[1]

        parser = None
        try:
            self._wait_turn()
            resp = self._session().get(f"https://{host}/robots.txt", timeout=15)
            if resp.status_code == 200:
                parser = RobotFileParser()
                parser.parse(resp.content.decode("utf-8", "replace").splitlines())
            elif 400 <= resp.status_code < 500:
                # RFC 9309：4xx 表示没有 robots.txt，视为完全放行
                # （实测 CVF 就是 404）
                parser = None
            else:
                parser = None
        except requests.RequestException:
            parser = None

        with self._state_lock:
            self._robots[host] = (time.monotonic(), parser)
        return parser
