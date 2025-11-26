# -*- coding: utf-8 -*-
"""
NgânMiu.Store — Shopee Cookie Checker (Live/Die + GTC)
Giao diện chỉ còn 3 nút:
- 🔎 Check
- 🟢 Lọc Đơn GTC (.txt)
- 🟡 Lọc Đơn Chưa GTC (.txt)
"""

from flask import request, jsonify, Response   # bỏ Flask, không cần app riêng

import httpx, concurrent.futures as cf, threading, time, re
from typing import Any, Dict, List, Tuple, Union

# =========================== CONFIG ===========================
BASE = "https://shopee.vn/api/v4"
ORDER_LIST_LIMIT = 5
HTTP_TIMEOUT = 10.0
POOL_WORKERS = 24
DETAIL_WORKERS_PER_COOKIE = 5

DEFAULT_HEADERS = {
    "User-Agent": "Android app Shopee appver=28320 app_type=1",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Accept-Language": "vi-VN,vi;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "If-None-Match-": "*",
}

# ========================= APP & STATE =========================
_last = {"results": [], "updated": 0.0}
_last_lock = threading.Lock()

# ========================= HTML (UI) ===========================
TEMPLATE = """
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NgânMiu.Store — Check Cookie Shopee</title>
<style>
 :root{ --brand:#EE4D2D; --border:#eaeaea; }
 body{font-family:Arial,Helvetica,sans-serif;background:#fff;margin:0}
 .topbar{background:var(--brand);color:#fff;padding:14px 20px;font-weight:700}
 .wrap{max-width:980px;margin:16px auto 40px;padding:16px;border:1px solid var(--border);
       border-radius:10px;box-shadow:0 6px 20px rgba(0,0,0,.06)}
 label.small{font-size:12px;color:#6b7280}
 textarea{width:100%;height:160px;padding:12px;font-size:14px;border-radius:8px;border:1px solid var(--border);resize:vertical}
 .controls{margin-top:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
 button{padding:8px 14px;border-radius:8px;border:1px solid var(--border);cursor:pointer;font-weight:600}
 .btn-check{background:#0b75c9;color:#fff;border-color:#0b75c9}
 .btn-export-gtc{background:#22c55e;color:#fff;border-color:#22c55e}
 .btn-export-not{background:#f59e0b;color:#fff;border-color:#f59e0b}
 .results{margin-top:16px;font-size:14px}
 table{width:100%;border-collapse:collapse;margin-top:8px}
 th,td{padding:8px 10px;border:1px solid var(--border);text-align:left;font-size:13px;vertical-align:top}
 tr.delivered{background:#ecffef}
 tr.dead{background:#fff1f0;color:#7a1a1a}
 .spinner{display:inline-block;width:16px;height:16px;border:2px solid #f3f3f3;border-top:2px solid #0b75c9;border-radius:50%;animation:spin .8s linear infinite}
 @keyframes spin{to{transform:rotate(360deg)}}
 .muted{color:#6b7280;font-size:12px}
 .mono{font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;}
</style>
</head>
<body>
  <div class="topbar">NgânMiu.Store — Tra cứu Cookie Shopee</div>

  <div class="wrap">
    <label class="small">Dán nhiều cookie (mỗi dòng 1 cookie: SPC_ST=… hoặc chỉ token SPC_ST)</label>
    <textarea id="cookiesInput" class="mono" placeholder="SPC_ST=abc...
SPC_ST=xyz..."></textarea>

    <div class="controls">
      <button id="btnCheck" class="btn-check">🔎 Check</button>
      <button id="btnExportGTC" class="btn-export-gtc">🟢 Lọc Đơn GTC (.txt)</button>
      <button id="btnExportNotGTC" class="btn-export-not">🟡 Lọc Đơn Chưa GTC (.txt)</button>
      <div style="margin-left:auto" id="statusBox" class="muted"></div>
    </div>

    <div class="results" id="resultsArea"></div>
  </div>

<script>
async function postJSON(url, data){
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(data)});
  return r.json();
}
function lines(s){ return (s||"").split("\\n").map(x=>x.trim()).filter(Boolean); }
function downloadText(filename, content){
  const blob = new Blob([content], {type:'text/plain;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href=url; a.download=filename;
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
}
function table(items){
  if(!items.length) return '<div class="muted">Chưa có kết quả. Nhấn Check để bắt đầu.</div>';
  let h = '<table><thead><tr><th>#</th><th>Cookie (rút gọn)</th><th>Live?</th><th>Giao thành công?</th><th>MVĐ</th><th>Trạng thái</th><th>Ghi chú</th></tr></thead><tbody>';
  items.forEach((it,i)=>{
    const cls = !it.live ? "dead" : (it.has_delivered ? "delivered" : "");
    const shortCk = (it.original || it.cookie || '').slice(0,44) + ((it.original||it.cookie||'').length>44?'...':'');
    h += `<tr class="${cls}"><td>${i+1}</td><td class="mono">${shortCk}</td><td>${it.live?'✅':'❌'}</td><td>${it.has_delivered?'✅':'—'}</td><td class="mono">${it.waybill||'—'}</td><td>${it.status_text||'—'}</td><td>${it.note||''}</td></tr>`;
  });
  return h + '</tbody></table>';
}

document.getElementById('btnCheck').addEventListener('click', async ()=>{
  const arr = lines(document.getElementById('cookiesInput').value);
  if(!arr.length){ alert('Vui lòng dán ít nhất 1 cookie'); return; }
  document.getElementById('statusBox').innerHTML = '<span class="spinner"></span> Đang kiểm tra...';
  document.getElementById('resultsArea').innerHTML = '';
  try{
    const resp = await postJSON('/api/check', {cookies: arr});
    window.__lastResults = resp.results || [];
    document.getElementById('statusBox').innerText = `Checked ${resp.results.length} cookies — ${resp.elapsed.toFixed(2)}s`;
    document.getElementById('resultsArea').innerHTML = table(window.__lastResults);
  }catch(e){
    console.error(e); alert('Lỗi khi gọi server');
  }finally{
    if(!document.getElementById('resultsArea').innerHTML) document.getElementById('statusBox').innerText='';
  }
});

document.getElementById('btnExportGTC').addEventListener('click', ()=>{
  const arr = window.__lastResults || [];
  if(!arr.length){ alert('Hãy nhấn Check trước!'); return; }
  const lines = arr.filter(x=>x.has_delivered).map(x=>x.original || x.cookie).filter(Boolean);
  if(!lines.length){ alert('Không có cookie GTC trong kết quả gần nhất.'); return; }
  downloadText('cookies_GTC.txt', lines.join('\\n'));
  document.getElementById('statusBox').innerText = `Đã xuất ${lines.length} cookie GTC`;
});

document.getElementById('btnExportNotGTC').addEventListener('click', ()=>{
  const arr = window.__lastResults || [];
  if(!arr.length){ alert('Hãy nhấn Check trước!'); return; }
  const lines = arr.filter(x=>x.live && !x.has_delivered).map(x=>x.original || x.cookie).filter(Boolean);
  if(!lines.length){ alert('Không có cookie "chưa GTC" trong kết quả gần nhất.'); return; }
  downloadText('cookies_chua_GTC.txt', lines.join('\\n'));
  document.getElementById('statusBox').innerText = `Đã xuất ${lines.length} cookie chưa GTC`;
});
</script>
</body>
</html>
"""

# ===================== HELPERS (HTTP + JSON) =====================
Json = Union[Dict[str, Any], List[Any]]

def normalize_cookie(line: str) -> str:
    s = (line or "").strip()
    if not s: return ""
    if "SPC_ST=" in s:
        v = s.split("SPC_ST=", 1)[1]
        for sep in (";", " "):
            if sep in v: v = v.split(sep, 1)[0]
        return "SPC_ST=" + v
    return "SPC_ST=" + s

def build_headers(cookie: str) -> Dict[str, str]:
    h = dict(DEFAULT_HEADERS); h["Cookie"] = normalize_cookie(cookie); return h

def http_get(url: str, headers: Dict[str, str], params: Dict[str, Any] | None = None) -> Tuple[int, Any]:
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as cli:
            r = cli.get(url, headers=headers, params=params)
            if r.status_code == 200:
                try: return 200, r.json()
                except Exception: return 200, {}
            return r.status_code, {}
    except Exception:
        return 0, {}

def is_session_invalid(payload: Any) -> bool:
    """Đánh dấu die khi response báo lỗi phiên/cookie."""
    if not isinstance(payload, dict): return False
    err = payload.get("error", None)
    msg = str(payload.get("error_msg", "") or "").strip().lower()
    if isinstance(err, int) and err != 0: return True
    if isinstance(err, str):
        em = err.strip().lower()
        if em and em not in ("0","ok","success"): return True
    if msg and msg not in ("ok","success"): return True
    data = payload.get("data", {})
    if isinstance(data, dict):
        derr = data.get("error")
        dmsg = str(data.get("error_msg","") or "").strip().lower()
        if derr not in (None,0,"0","ok","success"): return True
        if dmsg and dmsg not in ("ok","success"): return True
    top = {str(k).lower() for k in payload.keys()}
    if "data" in top and ("error" in top or "error_msg" in top) and not payload.get("data"):
        return True
    return False

def bfs_values_by_key(data: Json, keys=("order_id","order_sn","ordersn")) -> List[str]:
    out: List[str] = []; q: List[Json] = [data]; seen=set()
    while q:
        node=q.pop(0)
        if id(node) in seen: continue
        seen.add(id(node))
        if isinstance(node, dict):
            for k,v in node.items():
                if str(k).lower() in keys:
                    sv=str(v).strip()
                    if sv and sv not in out:
                        out.append(sv)
                        if len(out)>=ORDER_LIST_LIMIT: return out
                if isinstance(v,(dict,list)): q.append(v)
        elif isinstance(node,list):
            for it in node:
                if isinstance(it,(dict,list)): q.append(it)
    return out

# -------- status keywords (strict) --------
POSITIVE_STATUS = [
    "giao hàng thành công","giao thành công","đã giao","đã phát thành công","đã giao hàng",
    "delivered","delivered successfully","delivery successful",
]
NEGATIVE_HINTS = [
    "đến kho","đã đến kho","đang giao","đang vận chuyển","đang giao hàng",
    "chuẩn bị","chuẩn bị hàng","chuẩn bị giao","đang xử lý",
    "in transit","arrived at hub","arrived at facility","out for delivery","processing","chờ lấy hàng",
]
DONE_CODES = {6,7,8,9}

def deep_iter(o: Any):
    if isinstance(o, dict):
        for k,v in o.items():
            yield k,v
            yield from deep_iter(v)
    elif isinstance(o, list):
        for it in o: yield from deep_iter(it)

def extract_waybill(detail_json: Dict[str, Any]) -> str:
    candidates = ["tracking_number","trackingNo","tracking_no","trackingno","waybill","waybill_no",
                  "waybill_number","awb","billcode","spx_awb","shipping_document_number","shipment_tracking_number"]
    root = detail_json.get("data", detail_json)
    for k,v in deep_iter(root):
        if str(k).lower() in [c.lower() for c in candidates] and isinstance(v,(str,int)):
            sv=str(v).strip()
            if sv: return sv
    return ""

def extract_status_text(detail_json: Dict[str, Any]) -> str:
    priority = ["status_text","order_status_text","shipment_status_text","status_msg","delivery_text",
                "current_status_text","tracking_status","description","desc"]
    root = detail_json.get("data", detail_json)
    for k,v in deep_iter(root):
        lk=str(k).lower()
        if lk in priority and isinstance(v,(str,int)):
            sv=str(v).strip()
            if sv: return sv
    for k,v in deep_iter(root):
        if str(k).lower() in ("order_status","status","shipment_status","logistics_status","delivery_status") and isinstance(v,int):
            return f"Mã trạng thái: {v}"
    return ""

def _as_ts(v: Any)->int:
    try:
        s=str(v).strip()
        if not s: return 0
        n=int(float(s))
        if n>10_000_000_000: n//=1000
        return n if n>0 else 0
    except Exception: return 0

def _collect_status_events(detail_json: Dict[str, Any]) -> List[Tuple[int,str,int]]:
    root = detail_json.get("data", detail_json); arrays=[]
    def walk(o):
        if isinstance(o, dict):
            for k,v in o.items():
                lk=str(k).lower()
                if isinstance(v,list) and any(x in lk for x in ["track","tracking","timeline","history","events","logs"]):
                    arrays.append(v)
                elif isinstance(v,(dict,list)): walk(v)
        elif isinstance(o,list):
            for it in o: walk(it)
    walk(root)
    events=[]
    def read_item(it)->Tuple[int,str,int]:
        ts,txt,code=0,"",-1
        if isinstance(it, dict):
            for k,v in it.items():
                lk=str(k).lower()
                if lk in ("time","ctime","ts","timestamp","update_time","created_at","updated_at"): ts=max(ts,_as_ts(v))
                if lk in ("status_text","desc","description","text","message","status","state"):
                    t=str(v).strip()
                    if len(t)>len(txt): txt=t
                if lk in ("status_code","order_status","shipment_status","logistics_status","delivery_status","code"):
                    try: code=int(v)
                    except: 
                        sv=str(v).strip()
                        if sv.isdigit(): code=int(sv)
        return ts,txt,code
    for arr in arrays:
        for item in arr:
            if isinstance(item, dict):
                ts,txt,code=read_item(item)
                if ts or txt or code!=-1: events.append((ts,txt,code))
    if not events:
        txt=extract_status_text(detail_json); code=-1
        for k,v in deep_iter(root):
            lk=str(k).lower()
            if lk in ("order_status","status","shipment_status","logistics_status","delivery_status") and isinstance(v,int):
                code=v
        events.append((_as_ts(root.get("update_time",0)), txt, code))
    return events

def latest_status(detail_json: Dict[str, Any])->Tuple[str,int]:
    ev=_collect_status_events(detail_json)
    if not ev: return "",-1
    ev.sort(key=lambda x:(x[0],len(x[1])), reverse=True)
    return ev[0][1], ev[0][2]

def is_delivered(detail_json: Dict[str, Any])->bool:
    txt, code = latest_status(detail_json)
    if isinstance(code,int) and code in DONE_CODES: return True
    s=(txt or "").strip().lower()
    return bool(s and any(p in s for p in POSITIVE_STATUS) and not any(n in s for n in NEGATIVE_HINTS))

# ===================== CORE: CHECK ONE COOKIE =====================
def fetch_orders_and_details(cookie: str, limit: int = ORDER_LIST_LIMIT, offset: int = 0)->Dict[str,Any]:
    headers=build_headers(cookie)
    list_url=f"{BASE}/order/get_all_order_and_checkout_list"
    s1, j1 = http_get(list_url, headers, params={"limit":limit,"offset":offset})
    if s1 != 200:
        return {"live": False, "details": [], "note": f"List HTTP {s1}"}
    if is_session_invalid(j1):
        return {"live": False, "details": [], "note": "Cookie hết hạn/bị khóa"}

    ids = bfs_values_by_key(j1, ("order_id","order_sn","ordersn")) if isinstance(j1,(dict,list)) else []
    if not ids:
        # Không có đơn → theo yêu cầu: đánh đỏ
        return {"live": False, "details": [], "note": "Không có đơn/không thấy order_id, order_sn"}

    live = True
    detail_url=f"{BASE}/order/get_order_detail"
    def do_detail(oid: str)->Dict[str,Any]:
        param="order_id" if str(oid).strip().isdigit() and len(str(oid).strip())>=8 else "order_sn"
        s,j=http_get(detail_url, headers, params={param:oid})
        return {"id":oid, "ok":(s==200), "json":j}
    details=[]
    with cf.ThreadPoolExecutor(max_workers=DETAIL_WORKERS_PER_COOKIE) as pool:
        futs=[pool.submit(do_detail, oid) for oid in ids[:limit]]
        for f in cf.as_completed(futs):
            try: details.append(f.result())
            except Exception as e: details.append({"id":"", "ok":False, "json":{}, "err":str(e)})
    return {"live": live, "details": details, "note": ""}

def decide_summary(detail_items: List[Dict[str,Any]])->Tuple[bool,str,str]:
    delivered=False; waybill=""; status_text=""
    for it in detail_items:
        if not it.get("ok"): continue
        j=it.get("json",{})
        if not waybill: waybill=extract_waybill(j) or waybill
        if not status_text: status_text = latest_status(j)[0] or status_text
        if is_delivered(j):
            delivered=True
            st2,_=latest_status(j); status_text = st2 or status_text
            wb2=extract_waybill(j); waybill = wb2 or waybill
            break
    return delivered, (waybill or ""), (status_text or "—")

def check_one_cookie(cookie_line: str)->Dict[str,Any]:
    ck=normalize_cookie(cookie_line)
    out={"original":cookie_line,"cookie":ck,"cookie_short":(ck[:44]+"...") if len(ck)>44 else ck,
         "live":False,"has_delivered":False,"waybill":"","status_text":"","note":""}
    try:
        res=fetch_orders_and_details(ck, ORDER_LIST_LIMIT, 0)
        out["live"]=bool(res.get("live"))
        delivered,wb,st = decide_summary(res.get("details",[]))
        out["has_delivered"]=delivered; out["waybill"]=wb; out["status_text"]=st or ("—" if delivered else "—")
        out["note"]=res.get("note","") or ("Có đơn GTC" if delivered else "Chưa thấy GTC trong các đơn gần đây")
    except Exception as e:
        out["note"]=f"Err: {e}"
    return out

# ============================= ROUTES =============================

def api_check():
    payload=request.get_json(silent=True) or {}
    cookies=payload.get("cookies",[])
    if not isinstance(cookies,list): return jsonify({"error":"cookies must be list"}),400
    start=time.time()
    results=[]
    with cf.ThreadPoolExecutor(max_workers=POOL_WORKERS) as pool:
        futs=[pool.submit(check_one_cookie, c) for c in cookies]
        for f in cf.as_completed(futs):
            try: results.append(f.result())
            except Exception as e:
                results.append({"original":"","cookie":"","cookie_short":"","live":False,"has_delivered":False,"waybill":"","status_text":"","note":f"Exc: {e}"})
    elapsed=time.time()-start
    with _last_lock:
        _last["results"]=results; _last["updated"]=time.time()
    return jsonify({"elapsed":elapsed,"count":len(results),"results":results})

# (Không cần /api/last vì export dùng dữ liệu ở client — window.__lastResults)

