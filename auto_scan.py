#!/usr/bin/env python3
"""Clash 自动换节点 + ChatGPT Team 促销码批量验证 + 价格收集

自动检测 Clash 当前模式（规则/全局），对每个地区：
  1. 查找并切换到对应节点
  2. 调用 checkout API 生成 Stripe 支付 URL
  3. 调用 metadata API 获取折扣信息
  4. 获取无促销码的基础价格（用于对比）
  5. 自动换算 USD 等价（实时汇率）
  6. 汇总所有可用码 + 价格信息 + USD 对比

价格收集原理:
  - Metadata API → 折扣金额（本地货币）和时长
  - Checkout API (无促销码) → 基础价格 Stripe URL
  - 实时汇率 API → 换算 USD 等价
  - 结合三者 = 完整价格画像

用法:
  python auto_scan.py                     # 全自动扫描所有地区（含价格）
  python auto_scan.py US                  # 只扫描指定地区
  python auto_scan.py --list              # 列出支持的地区
  python auto_scan.py --open GB           # 扫描后自动打开浏览器
  python auto_scan.py --no-price          # 跳过价格收集（更快）
"""
import json
import os
import sys
import time
import webbrowser
from urllib.parse import quote
from urllib.request import Request, urlopen
from datetime import datetime

import config

# ─── 配置 ────────────────────────────────────────────────────

CLASH_CONTROLLER = config.get_clash_controller().rstrip("/")
CLASH_SECRET = config.get_clash_secret()
PROXY_URL = config.get_proxy_url()
REQUEST_DELAY = 0.8
OUTPUT_DIR = config.get_output_dir()

# ─── 地区定义 ────────────────────────────────────────────────

REGIONS = {
    "GB": {
        "keywords": ["英国", "🇬🇧"],
        "codes": [("aibuildgroupgb", "GB", "GBP"), ("talentgeniusuk", "GB", "GBP"), ("datroaiuk", "GB", "GBP")],
        "label": "🇬🇧 英国",
    },
    "AU": {
        "keywords": ["澳洲", "澳大利亚", "🇦🇺"],
        "codes": [("talentgeniusau", "AU", "AUD")],
        "label": "🇦🇺 澳洲",
    },
    "DE": {
        "keywords": ["德国", "🇩🇪"],
        "codes": [("codestonede", "DE", "EUR")],
        "label": "🇩🇪 德国",
    },
    "FR": {
        "keywords": ["法国", "🇫🇷"],
        "codes": [("codestonefr", "FR", "EUR"), ("wildmangofr", "FR", "EUR"), ("noranalytosfr", "FR", "EUR")],
        "label": "🇫🇷 法国",
    },
    "ES": {
        "keywords": ["西班牙", "🇪🇸"],
        "codes": [("codestonees", "ES", "EUR")],
        "label": "🇪🇸 西班牙",
    },
    "CA": {
        "keywords": ["加拿大", "🇨🇦"],
        "codes": [("talentgeniusca", "CA", "CAD"), ("monicaica", "CA", "CAD"), ("datroaica", "CA", "CAD"), ("noranalytosca", "CA", "CAD")],
        "label": "🇨🇦 加拿大",
    },
    "BR": {
        "keywords": ["巴西", "🇧🇷"],
        "codes": [("talentgeniusbr", "BR", "BRL")],
        "label": "🇧🇷 巴西",
    },
    "NZ": {
        "keywords": ["新西兰", "🇳🇿"],
        "codes": [("firstfocusnz", "NZ", "NZD")],
        "label": "🇳🇿 新西兰",
    },
    "KE": {
        "keywords": ["肯尼亚", "🇰🇪"],
        "codes": [("wildmangoke", "KE", "USD")],
        "label": "🇰🇪 肯尼亚",
    },
    "ZA": {
        "keywords": ["南非", "🇿🇦"],
        "codes": [("wildmangoza", "ZA", "ZAR")],
        "label": "🇿🇦 南非",
    },
    "NG": {
        "keywords": ["尼日利亚", "🇳🇬"],
        "codes": [("wildmangong", "NG", "NGN")],
        "label": "🇳🇬 尼日利亚",
    },
    "TH": {
        "keywords": ["泰国", "🇹🇭"],
        "codes": [("thinkingmachinesth", "TH", "THB")],
        "label": "🇹🇭 泰国",
    },
    "SG": {
        "keywords": ["新加坡", "🇸🇬"],
        "codes": [("thinkingmachinessg", "SG", "SGD")],
        "label": "🇸🇬 新加坡",
    },
    "PH": {
        "keywords": ["菲律宾", "🇵🇭"],
        "codes": [("thinkingmachinesph", "PH", "PHP")],
        "label": "🇵🇭 菲律宾",
    },
    "IN": {
        "keywords": ["🇮🇳", "印度 "],
        "codes": [("noranalytosin", "IN", "INR")],
        "label": "🇮🇳 印度",
    },
    "JP": {
        "keywords": ["日本", "🇯🇵"],
        "codes": [("datroaijp", "JP", "JPY")],
        "label": "🇯🇵 日本",
    },
}

US_CODES = [
    ("thealloynetwork", "US", "USD"),
    ("alongsideus", "US", "USD"),
    ("monicaius", "US", "USD"),
    ("talentgeniusus", "US", "USD"),
    ("firstfocusus", "US", "USD"),
    ("wildmangous", "US", "USD"),
    ("trintelus", "US", "USD"),
    ("noranalytosus", "US", "USD"),
    ("infoseekaius", "US", "USD"),
    ("datroaius", "US", "USD"),
    ("vouchapius", "US", "USD"),
]

CURRENCY_SYMBOLS = {
    "USD": "$", "GBP": "£", "EUR": "€", "AUD": "A$", "CAD": "C$",
    "BRL": "R$", "NZD": "NZ$", "ZAR": "R", "NGN": "₦", "THB": "฿", "SGD": "S$", "PHP": "₱",
    "INR": "₹", "JPY": "¥",
}

# ChatGPT Team 各国家 2 人月付基价（税前）
BASE_2_SEAT_PRICES = {
    "US": {"amount": 50, "currency": "USD"},
    "CA": {"amount": 68, "currency": "CAD"},
    "GB": {"amount": 36, "currency": "GBP"},
    "AU": {"amount": 70, "currency": "AUD"},
    "BR": {"amount": 260, "currency": "BRL"},
    "NZ": {"amount": 82, "currency": "NZD"},
    "KE": {"amount": 50, "currency": "USD"},
    "ZA": {"amount": 800, "currency": "ZAR"},
    "NG": {"amount": 67200, "currency": "NGN"},
    "TH": {"amount": 1560, "currency": "THB"},
    "SG": {"amount": 64, "currency": "SGD"},
    "PH": {"amount": 2900, "currency": "PHP"},
    "FR": {"amount": 52, "currency": "EUR"},
    "DE": {"amount": 52, "currency": "EUR"},
    "ES": {"amount": 52, "currency": "EUR"},
    "IN": {"amount": 4500, "currency": "INR"},
    "JP": {"amount": 7670, "currency": "JPY"},
}

# ─── 汇率 ────────────────────────────────────────────────────

_exchange_rates = {}

def fetch_exchange_rates():
    """获取最新汇率（USD 为基准），失败时使用硬编码近似值"""
    global _exchange_rates
    if _exchange_rates:
        return _exchange_rates
    try:
        import urllib.request
        resp = urllib.request.urlopen(
            "https://open.er-api.com/v6/latest/USD", timeout=10
        )
        data = json.loads(resp.read())
        _exchange_rates = data["rates"]
        return _exchange_rates
    except Exception:
        # 硬编码近似汇率（2026-05）
        _exchange_rates = {
            "USD": 1, "GBP": 0.73, "EUR": 0.85, "AUD": 1.38,
            "CAD": 1.37, "BRL": 4.92, "NZD": 1.68, "ZAR": 16.39,
            "NGN": 1360, "INR": 83.5, "JPY": 150, "THB": 36, "SGD": 1.34, "PHP": 58,
        }
        return _exchange_rates


def to_usd(amount, currency):
    """将本地货币金额转换为 USD"""
    rates = fetch_exchange_rates()
    rate = rates.get(currency)
    if not rate or currency == "USD":
        return round(amount, 2)
    return round(amount / rate, 2)


# ─── Clash API ───────────────────────────────────────────────

def _curl(path, method="GET", data=None):
    body = None
    headers = {}
    if data:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if CLASH_SECRET:
        headers["Authorization"] = f"Bearer {CLASH_SECRET}"

    req = Request(f"{CLASH_CONTROLLER}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        return None


def get_clash_mode():
    raw = _curl("/configs")
    if not raw:
        return "rule"
    try:
        return json.loads(raw).get("mode", "rule")
    except Exception:
        return "rule"


def get_proxy_group():
    import config as cfg
    mode = get_clash_mode()
    return cfg.get_proxy_group(mode)


def list_nodes():
    raw = _curl("/proxies")
    if not raw:
        return "?", []
    try:
        data = json.loads(raw)
    except Exception:
        return "?", []
    proxies = data.get("proxies", {})
    group = proxies.get(get_proxy_group(), {})
    current = group.get("now", "?")
    nodes = []
    skip_types = {"Selector", "URLTest", "Fallback", "Direct", "Reject", "Compatible", "Pass"}
    for name in group.get("all", []):
        info = proxies.get(name)
        if info and info.get("type") not in skip_types:
            nodes.append(name)
    return current, nodes


def test_latency(node):
    encoded = quote(node, safe="")
    r = _curl(f"/proxies/{encoded}/delay?timeout=5000&url=https://www.google.com")
    if not r:
        return -1
    try:
        return json.loads(r).get("delay", -1)
    except Exception:
        return -1


def switch_to(node):
    group = get_proxy_group()
    encoded = quote(group, safe="")
    _curl(f"/proxies/{encoded}", method="PUT", data={"name": node})


def get_current_node():
    raw = _curl("/proxies")
    if not raw:
        return "?"
    group = get_proxy_group()
    try:
        return json.loads(raw).get("proxies", {}).get(group, {}).get("now", "?")
    except Exception:
        return "?"


# ─── Token ───────────────────────────────────────────────────

def _get_token():
    """从 config 模块获取 accessToken"""
    import config as cfg
    return cfg.get_token()


# ─── HTTP 会话（curl_cffi 封装）────────────────────────────

def _make_session():
    from curl_cffi import requests as cffi_requests
    session = cffi_requests.Session(impersonate="chrome136")
    session.proxies = {"https": PROXY_URL, "http": PROXY_URL}
    return session


def _headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }


# ─── Checkout API ────────────────────────────────────────────

def try_checkout(code, country, currency):
    """调用 checkout API，返回 (url_or_None, status, err_msg, response_body)"""
    session = _make_session()
    payload = {
        "plan_name": "chatgptteamplan",
        "team_plan_data": {
            "workspace_name": f"Team{int(time.time())}",
            "price_interval": "month",
            "seat_quantity": 2,
        },
        "billing_details": {"country": country, "currency": currency},
        "promo_code": code,
        "cancel_url": "https://chatgpt.com/",
        "checkout_ui_mode": "hosted",
    }
    try:
        resp = session.post(
            "https://chatgpt.com/backend-api/payments/checkout",
            json=payload, headers=_headers(), timeout=20
        )
        data = resp.json()
        url = data.get("url") or ""
        if url.startswith("https://"):
            return url, resp.status_code, None, data
        return None, resp.status_code, data.get("detail", str(data)[:200]), data
    except Exception as e:
        return None, 0, str(e), {}


# ─── 价格收集 ────────────────────────────────────────────────

_metadata_cache = {}
_metadata_raw_cache = {}  # 保存原始 API 响应

def fetch_metadata(code):
    """调用 metadata API 获取折扣信息"""
    if code in _metadata_cache:
        return _metadata_cache[code]

    session = _make_session()
    url = f"https://chatgpt.com/backend-api/promotions/metadata/{code}?type=promo"
    try:
        resp = session.get(url, headers=_headers(), timeout=15)
        data = resp.json()
        meta = data.get("metadata") or data
        _metadata_cache[code] = meta
        _metadata_raw_cache[code] = data
        return meta
    except Exception:
        return None


def get_base_checkout(country, currency):
    """获取无促销码的基础价格 Stripe URL，返回 response dict"""
    session = _make_session()
    payload = {
        "plan_name": "chatgptteamplan",
        "team_plan_data": {
            "workspace_name": f"Team{int(time.time())}_base",
            "price_interval": "month",
            "seat_quantity": 2,
        },
        "billing_details": {"country": country, "currency": currency},
        "cancel_url": "https://chatgpt.com/",
        "checkout_ui_mode": "hosted",
    }
    try:
        resp = session.post(
            "https://chatgpt.com/backend-api/payments/checkout",
            json=payload, headers=_headers(), timeout=20
        )
        return resp.json()
    except Exception:
        return {}


def extract_price_info(meta, base_checkout_data, country_code=None):
    """整合 metadata + base checkout + 基价表，输出完整价格信息"""
    if not meta or not meta.get("discount"):
        return None

    discount = meta["discount"]
    discount_val = discount["value"]
    discount_ccy = discount["currency_code"]
    duration = meta.get("duration", {}).get("num_periods", "?")
    period = meta.get("duration", {}).get("period", "month")
    usd_equiv = to_usd(discount_val, discount_ccy)

    info = {
        "discount_amount": discount_val,
        "discount_currency": discount_ccy,
        "discount_usd": usd_equiv,
        "duration": f"{duration} {period}s",
    }

    # 从基价表计算实付和折扣率
    if country_code and country_code in BASE_2_SEAT_PRICES:
        bp = BASE_2_SEAT_PRICES[country_code]
        if bp["currency"] == discount_ccy:
            base_total = bp["amount"]
            base_per_seat = base_total // 2
            actual_total = round(base_total - discount_val, 2)
            discount_pct = round(discount_val / base_total * 100)
            actual_usd = round(to_usd(actual_total, discount_ccy))
            info["base_per_seat"] = base_per_seat
            info["base_2_total"] = base_total
            info["actual_price"] = actual_total
            info["actual_usd"] = actual_usd
            info["discount_pct"] = discount_pct

    if base_checkout_data.get("url"):
        info["base_url"] = base_checkout_data["url"]
        info["base_session_id"] = base_checkout_data.get("checkout_session_id")

    return info


def format_price_line(price_info):
    """格式化价格为可读文本"""
    if not price_info:
        return "?"
    d = price_info["discount_amount"]
    c = price_info["discount_currency"]
    sym = CURRENCY_SYMBOLS.get(c, c + " ")
    dur = price_info.get("duration", "?")
    return f"{sym}{d:.0f}/月 off x {dur}"


def format_usd_line(price_info):
    """格式化 USD 等价"""
    if not price_info or not price_info.get("discount_usd"):
        return ""
    u = price_info["discount_usd"]
    return f"${u:.0f}/月"


# ─── 核心扫描 ────────────────────────────────────────────────

def pick_best_node(nodes, keywords):
    matched = [n for n in nodes for kw in keywords if kw in n]
    if not matched:
        return None
    best, best_delay = None, 99999
    for n in matched:
        d = test_latency(n)
        if 0 < d < best_delay:
            best_delay = d
            best = n
    return best


def scan_region(code_list, country, currency, collect_price=True):
    """扫描一个地区的所有码，返回 [(code, url, price_info), ...]"""
    results = []

    # 先获取无促销码的基础价格
    base_data = {}
    if collect_price:
        bc = get_base_checkout(country, currency)
        if bc.get("url"):
            base_data = bc

    for code, c, cur in code_list:
        url, status, err, _ = try_checkout(code, c or country, cur or currency)

        price_info = None
        if url and collect_price:
            sys.stdout.write(f"    🔄 {code:<25s} 查询折扣...")
            sys.stdout.flush()
            meta = fetch_metadata(code)
            time.sleep(0.3)
            price_info = extract_price_info(meta, base_data, country)

            if price_info:
                detail = format_price_line(price_info)
                if "actual_price" in price_info:
                    sym = CURRENCY_SYMBOLS.get(price_info["discount_currency"], "")
                    detail += f" → {sym}{price_info['actual_price']:.0f}/月"
                    if price_info.get("actual_usd"):
                        detail += f" (${price_info['actual_usd']}/月)"
                    if price_info.get("discount_pct"):
                        detail += f" -{price_info['discount_pct']}%"
                print(f" {detail}")
            else:
                print(" 无折扣信息")
        elif url:
            print(f"    ✅ {code:<25s} URL 已生成")
        elif err:
            print(f"    ❌ {code:<25s} {err[:70]}")
        else:
            print(f"    ❌ {code:<25s} status={status}")

        results.append((code, url, price_info))
        time.sleep(REQUEST_DELAY)
    return results


def run_scan(target_region=None, auto_open=False, collect_price=True):
    """主扫描流程"""
    # 先验证 token 是否有效（防止过期 token 导致全部 false negative）
    import discover_codes as dc
    dc.validate_token()

    mode = get_clash_mode()
    group = get_proxy_group()
    current_node, all_nodes = list_nodes()

    print(f"\n{'='*60}")
    print(f"🔍 ChatGPT Team 促销码自动扫描")
    print(f"{'='*60}")
    print(f"  Clash: {mode.upper()} → {group}  |  节点: {current_node}")
    print(f"  可用节点: {len(all_nodes)}  |  价格收集: {'✅' if collect_price else '❌跳过'}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    working = []  # [(code, region_label, url, price_info)]

    # ── 扫描 US ──
    if not target_region or target_region == "US":
        us_node = pick_best_node(all_nodes, ["美国", "🇺🇸"])
        if us_node:
            print(f"\n{'─'*60}\n🇺🇸 美国 — 切换到: {us_node}\n{'─'*60}")
            switch_to(us_node)
            time.sleep(0.5)
            print(f"    当前: {get_current_node()}")
        else:
            print(f"\n⚠️  未找到美国节点，仍尝试 US 码")

        us_results = scan_region(
            [(c, co, cu) for c, co, cu in US_CODES],
            "US", "USD", collect_price
        )
        for code, url, price in us_results:
            if url:
                working.append((code, "US", url, price))

    # ── 扫描其他地区 ──
    for rc, region in sorted(REGIONS.items()):
        if target_region and rc != target_region:
            continue

        best = pick_best_node(all_nodes, region["keywords"])
        if not best:
            if target_region == rc:
                print(f"\n❌ 未找到 {region['label']} 的节点")
            continue

        latency = test_latency(best)
        print(f"\n{'─'*60}\n{region['label']} — 切换到: {best} ({latency}ms)\n{'─'*60}")
        switch_to(best)
        time.sleep(0.5)
        print(f"    当前: {get_current_node()}")

        bc = region["codes"][0]
        results = scan_region(region["codes"], bc[1], bc[2], collect_price)
        for code, url, price in results:
            if url:
                working.append((code, rc, url, price))

    # ── 汇总输出 ──
    print(f"\n{'='*60}")
    print(f"📊 扫描完成 — 共 {len(working)} 个可用码")
    print(f"{'='*60}")

    if not working:
        print("\n❌ 没有生成任何 Stripe URL\n")
        return

    # 终端输出表格
    print(f"\n{'促销码':<25s} {'地区':<6s} {'实付/月':<14s} {'折扣':<6s} {'≈ USD'}")
    print("-" * 70)
    for code, rc, url, price in working:
        if price and "actual_price" in price:
            sym = CURRENCY_SYMBOLS.get(price["discount_currency"], "")
            actual = f"{sym}{price['actual_price']:.0f}"
            pct = f"-{price['discount_pct']}%"
            usd_val = f"${price['actual_usd']}"
        else:
            actual = format_price_line(price) if price else "?"
            pct = ""
            usd_val = format_usd_line(price) if price else "?"
        print(f"  {code:<23s} {rc:<6s} {actual:<14s} {pct:<6s} {usd_val}")
    print()

    # 保存到文件
    _save_results(working, mode)

    # 切回 US
    if not target_region:
        us_node = pick_best_node(all_nodes, ["美国", "🇺🇸"])
        if us_node:
            switch_to(us_node)
            print(f"✅ 已切回 US 节点: {us_node}")

    # --open 打开浏览器
    if auto_open and target_region:
        print(f"\n🌐 打开浏览器...")
        for code, rc, url, _ in working:
            if rc == target_region or (target_region == "US" and rc == "US"):
                webbrowser.open(url)
                time.sleep(0.5)


def _save_results(working, mode):
    """保存扫描结果到 stripe_urls.txt、scan_results.json 和 metadata 缓存"""
    # ── TXT ──
    text_path = os.path.join(OUTPUT_DIR, "stripe_urls.txt")
    with open(text_path, "w") as f:
        f.write(f"ChatGPT Team 促销码 Stripe URL — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"共 {len(working)} 个可用码\n\n")
        for code, rc, url, price in working:
            f.write(f"[{rc}] {code}\n")
            if price and "actual_price" in price:
                sym = CURRENCY_SYMBOLS.get(price["discount_currency"], "")
                f.write(f"    实付: {sym}{price['actual_price']:.0f}/月  ({price['discount_pct']}% off)"
                        f"  ≈ ${price['actual_usd']}/月\n")
                f.write(f"    折扣: {price['discount_amount']}{sym} off x {price['duration']}\n")
            elif price:
                pl = format_price_line(price)
                usd = format_usd_line(price)
                f.write(f"    {pl}" + (f"  ({usd})" if usd else "") + "\n")
            f.write(f"    {url}\n\n")

    # ── JSON (带完整价格信息) ──
    json_path = os.path.join(OUTPUT_DIR, "scan_results.json")
    json_results = []
    for code, rc, url, price in working:
        entry = {"code": code, "region": rc, "stripe_url": url}
        if price:
            entry["price_info"] = price
        json_results.append(entry)

    scan_time = datetime.now().isoformat()
    with open(json_path, "w") as f:
        json.dump({
            "scan_time": scan_time,
            "clash_mode": mode,
            "total_working": len(working),
            "results": json_results,
        }, f, indent=2, ensure_ascii=False)

    # ── metadata 原始响应 ──
    if _metadata_raw_cache:
        meta_path = os.path.join(OUTPUT_DIR, "metadata_cache.json")
        with open(meta_path, "w") as f:
            json.dump({
                "last_updated": scan_time,
                "metadata": _metadata_raw_cache,
            }, f, indent=2, ensure_ascii=False)
        print(f"📝 已保存: {meta_path}")

    print(f"📝 已保存: {text_path}")
    print(f"📝 已保存: {json_path}")


def list_regions():
    print("\n支持的地区:")
    print(f"{'地区码':<8s} {'地区':<15s} {'促销码'}")
    print("-" * 40)
    print(f"{'US':<8s} {'🇺🇸 美国':<15s} {', '.join(c for c, _, _ in US_CODES)}")
    for rc, region in sorted(REGIONS.items()):
        cs = ", ".join(c for c, _, _ in region["codes"])
        print(f"{rc:<8s} {region['label']:<15s} {cs}")
    print()


# ─── 入口 ────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--list" in sys.argv:
        list_regions()
        sys.exit(0)

    target = None
    auto_open = "--open" in sys.argv
    collect_price = "--no-price" not in sys.argv

    for rc in list(REGIONS.keys()) + ["US"]:
        if rc in sys.argv:
            target = rc
            break

    if target:
        if target != "US" and target not in REGIONS:
            print(f"未知地区: {target}")
            sys.exit(1)

    run_scan(target_region=target, auto_open=auto_open, collect_price=collect_price)
