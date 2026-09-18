"""统一 HTTP 客户端。

设计要点：
- 磁盘缓存：开发期反复抓取时不会重复打平台接口，避免触发风控。
- 指数退避重试：B 站接口偶发抖动时自动重试。
- 浏览器指纹头：降低被识别为脚本的概率。
- 全部失败时抛出异常，由上层决定是否沿用旧快照。
"""

import gzip
import hashlib
import json
import os
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


class HttpError(Exception):
    def __init__(self, url, status, body):
        super().__init__("HTTP %s <- %s" % (status, url))
        self.url = url
        self.status = status
        self.body = body


class HttpClient:
    def __init__(self, cache_dir=None, ttl=21600, retries=3, timeout=25,
                 base_delay=1.5, delay=0.0, verbose=True):
        self.cache_dir = cache_dir
        self.ttl = ttl
        self.retries = retries
        self.timeout = timeout
        self.base_delay = base_delay
        self.delay = delay
        self.verbose = verbose
        self.stats = {"cache": 0, "net": 0, "fail": 0}
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def _log(self, msg):
        if self.verbose:
            print(msg, flush=True)

    def _cache_path(self, key):
        return os.path.join(self.cache_dir, hashlib.sha1(key.encode("utf-8")).hexdigest()[:24] + ".bin")

    def _read_cache(self, key):
        if not self.cache_dir or self.ttl <= 0:
            return None
        p = self._cache_path(key)
        if not os.path.exists(p):
            return None
        if time.time() - os.path.getmtime(p) > self.ttl:
            return None
        try:
            with open(p, "rb") as f:
                return f.read()
        except OSError:
            return None

    def _write_cache(self, key, body):
        if not self.cache_dir or self.ttl <= 0:
            return
        try:
            with open(self._cache_path(key), "wb") as f:
                f.write(body)
        except OSError:
            pass

    @staticmethod
    def _decompress(body, headers):
        enc = (headers.get("Content-Encoding") or "").lower()
        try:
            if "gzip" in enc:
                return gzip.decompress(body)
            if "deflate" in enc:
                return zlib.decompress(body, -zlib.MAX_WBITS)
        except Exception:
            return body
        return body

    def get(self, url, headers=None, referer=None, origin=None, cookie=None,
            raw=False, use_cache=True, timeout=None):
        """返回 bytes（raw=True）或解码后的 str。"""
        h = {
            "User-Agent": UA,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        }
        if referer:
            h["Referer"] = referer
        if origin:
            h["Origin"] = origin
        if cookie:
            h["Cookie"] = cookie
        if headers:
            h.update(headers)

        ck = url + "||" + json.dumps({k: v for k, v in h.items() if k != "User-Agent"},
                                     sort_keys=True, ensure_ascii=False)
        if use_cache:
            cached = self._read_cache(ck)
            if cached is not None:
                self.stats["cache"] += 1
                return cached if raw else cached.decode("utf-8", "replace")

        last_err = None
        for attempt in range(self.retries):
            if self.delay:
                time.sleep(self.delay + random.uniform(0, 0.4))
            try:
                req = urllib.request.Request(url, headers=h)
                with urllib.request.urlopen(req, timeout=timeout or self.timeout, context=_CTX) as r:
                    body = self._decompress(r.read(), r.headers)
                self.stats["net"] += 1
                self._write_cache(ck, body)
                return body if raw else body.decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                last_err = e
                body = b""
                try:
                    body = e.read()[:400]
                except Exception:
                    pass
                # 4xx（除 429）通常重试无意义
                if 400 <= e.code < 500 and e.code != 429:
                    self.stats["fail"] += 1
                    raise HttpError(url, e.code, body.decode("utf-8", "replace")) from None
            except Exception as e:  # noqa: BLE001 - 网络层统一兜底
                last_err = e
            if attempt < self.retries - 1:
                wait = self.base_delay * (2 ** attempt)
                self._log("    ! 重试 %d/%d（%s），%.1fs 后继续" % (attempt + 1, self.retries, last_err, wait))
                time.sleep(wait)
        self.stats["fail"] += 1
        raise HttpError(url, getattr(last_err, "code", None), str(last_err))

    def get_json(self, url, **kw):
        txt = self.get(url, **kw)
        try:
            return json.loads(txt)
        except ValueError:
            raise HttpError(url, None, txt[:200]) from None

    def report(self):
        s = self.stats
        return "缓存命中 %d / 实际请求 %d / 失败 %d" % (s["cache"], s["net"], s["fail"])
