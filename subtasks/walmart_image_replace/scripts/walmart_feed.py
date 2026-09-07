"""Walmart Marketplace Feed 客户端（真实 API）—— 用于图片替换的提交与对账。

设计要点：
- 纯标准库实现（xml.etree + urllib），不依赖 requests，方便离线逻辑测试。
- 网络调用集中在 get_token / submit_item_feed / get_feed_status / get_feed_items 四个方法，
  --dry-run 模式完全不调用它们，仅做 XML 构造、分组与解析逻辑，可用于离线逻辑测试。
- 沃尔玛 v3 鉴权：先用 client_id + client_secret 换 access_token（/v3/token），
  之后每次请求头同时带 Authorization: Basic base64(client_id:client_secret) 与 WM_SEC.ACCESS_TOKEN。

典型用法见 06_submit_replace.py / 07_reconcile.py。

离线自检：python scripts/walmart_feed.py   （构造/解析 XML，不触网）
"""

from __future__ import annotations

import base64
import json
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

WALMART_NS = "http://walmart.com/"


@dataclass
class StoreCreds:
    store_key: str
    base_url: str
    client_id: str | None
    client_secret: str | None

    def ready(self) -> bool:
        return bool(self.client_id and self.client_secret)


def _strip_ns(tag: str) -> str:
    """去掉 XML 命名空间前缀，返回本地标签名。"""
    return tag.split("}", 1)[-1]


# --------------------------------------------------------------------------- #
# XML 构造：把一批 SKU 的图片组装成沃尔玛 MPItemFeed
# --------------------------------------------------------------------------- #
def build_item_feed_xml(items: list[dict], request_id: str, version: str = "1.5.0") -> bytes:
    """构造 MPItemFeed XML（字节，含 XML 声明）。

    items: 元素为 {"sku", "gtin"(可选), "main_url", "alt_urls": [url, ...]}
    每个 SKU 输出一个 <MPItem>，用 AdditionalProductAttributes/ImageUrls 设置主图与顺序副图。
    注意：沃尔玛图片属性为「全量替换」，因此必须传入完整图片集（即 05 payload 的 final_images）。
    """
    ET.register_namespace("", WALMART_NS)
    root = ET.Element(f"{{{WALMART_NS}}}MPItemFeed")
    header = ET.SubElement(root, f"{{{WALMART_NS}}}MPItemFeedHeader")
    ET.SubElement(header, f"{{{WALMART_NS}}}version").text = version
    ET.SubElement(header, f"{{{WALMART_NS}}}requestId").text = request_id
    ET.SubElement(header, f"{{{WALMART_NS}}}requestBatchId").text = request_id

    for it in items:
        mp = ET.SubElement(root, f"{{{WALMART_NS}}}MPItem")
        ET.SubElement(mp, f"{{{WALMART_NS}}}sku").text = str(it["sku"])
        gtin = it.get("gtin")
        if gtin:
            pids = ET.SubElement(mp, f"{{{WALMART_NS}}}productIdentifiers")
            pid = ET.SubElement(pids, f"{{{WALMART_NS}}}productIdentifier")
            ET.SubElement(pid, f"{{{WALMART_NS}}}gtin").text = str(gtin)
        apa = ET.SubElement(mp, f"{{{WALMART_NS}}}AdditionalProductAttributes")
        attr = ET.SubElement(apa, f"{{{WALMART_NS}}}AdditionalProductAttribute")
        ET.SubElement(attr, f"{{{WALMART_NS}}}attributeName").text = "ImageUrls"
        av = ET.SubElement(attr, f"{{{WALMART_NS}}}attributeValue")
        iu = ET.SubElement(av, f"{{{WALMART_NS}}}ImageUrls")
        ET.SubElement(iu, f"{{{WALMART_NS}}}MainImageUrl").text = str(it["main_url"])
        for i, url in enumerate(it.get("alt_urls", []), start=1):
            alt = ET.SubElement(iu, f"{{{WALMART_NS}}}AlternateImageUrl")
            alt.set("sequence", str(i))
            alt.text = str(url)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# --------------------------------------------------------------------------- #
# 响应解析
# --------------------------------------------------------------------------- #
def parse_feed_id(xml_text: str) -> str:
    root = ET.fromstring(xml_text)
    for el in root.iter():
        if _strip_ns(el.tag) == "feedId" and el.text:
            return el.text.strip()
    raise RuntimeError("沃尔玛 Feed 响应中未找到 <feedId>")


def parse_feed_status(xml_text: str) -> dict[str, Any]:
    """解析 GET /v3/feeds/{feedId} 的响应，返回摘要字典。"""
    root = ET.fromstring(xml_text)
    text = lambda tag: _first_text(root, tag)
    errors = _parse_ingestion_errors(root)
    return {
        "feedId": text("feedId"),
        "feedStatus": text("feedStatus"),
        "itemsReceived": _to_int(text("itemsReceived")),
        "itemsSucceeded": _to_int(text("itemsSucceeded")),
        "itemsFailed": _to_int(text("itemsFailed")),
        "itemsProcessing": _to_int(text("itemsProcessing")),
        "ingestionErrors": errors,
    }


def parse_feed_items(xml_text: str) -> tuple[list[dict[str, Any]], int | None]:
    """解析 GET /v3/feeds/{feedId}/items 的单页响应。

    返回 (items, totalCount)。items 元素: {sku, index, ingestionStatus, errors:[...]}
    """
    root = ET.fromstring(xml_text)
    total = root.attrib.get("totalCount")
    total = int(total) if total and total.isdigit() else None
    out: list[dict[str, Any]] = []
    for item in root.iter():
        if _strip_ns(item.tag) != "item":
            continue
        sku = _first_text(item, "sku") or ""
        index = _first_text(item, "index") or ""
        status = _first_text(item, "ingestionStatus") or _first_text(item, "status") or ""
        out.append({
            "sku": sku,
            "index": index,
            "ingestionStatus": status,
            "errors": _parse_ingestion_errors(item),
        })
    return out, total


def _first_text(parent: ET.Element, local_tag: str) -> str | None:
    for el in parent.iter():
        if _strip_ns(el.tag) == local_tag and el.text:
            return el.text.strip()
    return None


def _parse_ingestion_errors(scope: ET.Element) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for err in scope.iter():
        if _strip_ns(err.tag) != "ingestionError":
            continue
        errors.append({
            "type": _first_text(err, "type") or "",
            "code": _first_text(err, "code") or "",
            "description": _first_text(err, "description") or "",
            "severity": _first_text(err, "severity") or "",
            "errorField": _first_text(err, "errorField") or "",
        })
    return errors


def _to_int(v: str | None) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# 客户端
# --------------------------------------------------------------------------- #
class WalmartClient:
    def __init__(
        self,
        creds: StoreCreds,
        token_endpoint: str = "/v3/token",
        feed_endpoint: str = "/v3/feeds",
        token_cache_seconds: int = 900,
        timeout: int = 60,
    ) -> None:
        self.creds = creds
        self.token_endpoint = token_endpoint
        self.feed_endpoint = feed_endpoint
        self.token_cache_seconds = token_cache_seconds
        self.timeout = timeout
        self._token: str | None = None
        self._token_at: float = 0.0

    # ----- 鉴权 ----- #
    def _basic_headers(self, *, with_token: bool = True) -> dict[str, str]:
        h = {
            "WM_SVC.NAME": "Walmart Marketplace",
            "WM_QOS.CORRELATION_ID": str(uuid.uuid4()),
            "Accept": "application/xml",
        }
        if self.creds.client_id and self.creds.client_secret:
            basic = base64.b64encode(
                f"{self.creds.client_id}:{self.creds.client_secret}".encode()
            ).decode()
            h["Authorization"] = f"Basic {basic}"
        if with_token and self._token:
            h["WM_SEC.ACCESS_TOKEN"] = self._token
        return h

    def get_token(self, force: bool = False) -> str:
        now = time.time()
        if self._token and not force and (now - self._token_at) < self.token_cache_seconds:
            return self._token
        if not self.creds.ready():
            raise RuntimeError(
                f"店铺 {self.creds.store_key} 缺少 Walmart 凭证（client_id / client_secret）"
            )
        url = f"{self.creds.base_url}{self.token_endpoint}"
        data = urlencode({
            "grant_type": "client_credentials",
            "client_id": self.creds.client_id,
            "client_secret": self.creds.client_secret,
        }).encode()
        req = Request(url, data=data, method="POST")
        req.add_header("WM_SVC.NAME", "Walmart Marketplace")
        req.add_header("WM_QOS.CORRELATION_ID", str(uuid.uuid4()))
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except URLError as e:
            raise RuntimeError(f"获取 Walmart token 失败（{url}）：{e}") from e
        parsed = json.loads(body)
        self._token = parsed["access_token"]
        self._token_at = now
        return self._token

    # ----- Feed 提交 ----- #
    def submit_item_feed(self, xml_bytes: bytes) -> str:
        self.get_token()
        url = f"{self.creds.base_url}{self.feed_endpoint}?feedType=item"
        req = Request(url, data=xml_bytes, method="POST")
        for k, v in self._basic_headers().items():
            req.add_header(k, v)
        req.add_header("Content-Type", "application/xml")
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except URLError as e:
            raise RuntimeError(f"提交沃尔玛 Feed 失败（{url}）：{e}") from e
        return parse_feed_id(body)

    # ----- Feed 状态查询 ----- #
    def get_feed_status(self, feed_id: str) -> dict[str, Any]:
        self.get_token()
        url = f"{self.creds.base_url}{self.feed_endpoint}/{feed_id}"
        req = Request(url, method="GET")
        for k, v in self._basic_headers(with_token=True).items():
            req.add_header(k, v)
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except URLError as e:
            raise RuntimeError(f"查询沃尔玛 Feed 状态失败（{url}）：{e}") from e
        return parse_feed_status(body)

    def get_feed_items(self, feed_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """分页拉取 feed 内每个 SKU 的处理结果，按 sku 聚合。"""
        self.get_token()
        all_items: list[dict[str, Any]] = []
        offset = 0
        while True:
            url = (
                f"{self.creds.base_url}{self.feed_endpoint}/{feed_id}/items"
                f"?limit={limit}&offset={offset}"
            )
            req = Request(url, method="GET")
            for k, v in self._basic_headers(with_token=True).items():
                req.add_header(k, v)
            try:
                with urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8")
            except URLError as e:
                raise RuntimeError(f"查询沃尔玛 Feed 明细失败（{url}）：{e}") from e
            page, total = parse_feed_items(body)
            all_items.extend(page)
            if not page:
                break
            offset += len(page)
            if total is not None and offset >= total:
                break
            if offset > 200000:  # 保险，避免异常死循环
                break
        return all_items


# --------------------------------------------------------------------------- #
# 离线自检（python scripts/walmart_feed.py）
# --------------------------------------------------------------------------- #
def _self_test() -> None:
    items = [{
        "sku": "TEST_SKU_1",
        "gtin": "00064301512334",
        "main_url": "https://example.com/main.jpg",
        "alt_urls": ["https://example.com/1.jpg", "https://example.com/2.jpg"],
    }]
    xml = build_item_feed_xml(items, "self-test-req")
    assert xml.startswith(b"<?xml"), "XML 声明缺失"
    root = ET.fromstring(xml)
    assert _strip_ns(root.tag) == "MPItemFeed"
    mps = [e for e in root.iter() if _strip_ns(e.tag) == "MPItem"]
    assert len(mps) == 1
    alts = [e for e in root.iter() if _strip_ns(e.tag) == "AlternateImageUrl"]
    assert len(alts) == 2 and alts[0].get("sequence") == "1"

    status_xml = (
        '<?xml version="1.0"?><Feed xmlns="http://walmart.com/">'
        "<feedId>FEED123</feedId><feedStatus>PROCESSED</feedStatus>"
        "<itemsReceived>1</itemsReceived><itemsSucceeded>1</itemsSucceeded>"
        "<itemsFailed>0</itemsFailed><itemsProcessing>0</itemsProcessing></Feed>"
    )
    st = parse_feed_status(status_xml)
    assert st["feedId"] == "FEED123" and st["feedStatus"] == "PROCESSED"

    items_xml = (
        '<?xml version="1.0"?><items xmlns="http://walmart.com/" totalCount="1">'
        "<item><sku>T1</sku><index>1</index><ingestionStatus>SUCCESS</ingestionStatus></item>"
        "</items>"
    )
    parsed, total = parse_feed_items(items_xml)
    assert total == 1 and parsed[0]["sku"] == "T1" and parsed[0]["ingestionStatus"] == "SUCCESS"

    err_xml = (
        '<?xml version="1.0"?><items xmlns="http://walmart.com/" totalCount="1">'
        "<item><sku>BAD</sku><index>1</index><ingestionStatus>DATA_ERROR</ingestionStatus>"
        "<ingestionErrors><ingestionError><type>BUSINESS</type><code>INVALID_IMAGE</code>"
        "<description>image not reachable</description><severity>ERROR</severity>"
        "</ingestionError></ingestionErrors></item></items>"
    )
    pe, _ = parse_feed_items(err_xml)
    assert pe[0]["errors"] and pe[0]["errors"][0]["code"] == "INVALID_IMAGE"

    print("walmart_feed 离线自检通过：XML 构造 / 状态解析 / 明细解析 均正常")


if __name__ == "__main__":
    _self_test()
