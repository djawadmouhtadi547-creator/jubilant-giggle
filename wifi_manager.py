import json, os, re, sys, threading, time, base64, urllib.parse, urllib.request
import tkinter as tk
from tkinter import ttk, simpledialog
from datetime import datetime

DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
DEF = {"host": "192.168.1.1", "user": "admin", "pass": "admin", "interval": 15, "known": [], "names": {},
       "p_dhcp": "/dhcpinfo.html", "p_wifi": "/wlstationlist.cmd", "p_tod": "/todmngr.tmp",
       "p_add": "/todadd.cmd", "p_del": "/todmngr.cmd"}
MAC = re.compile(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}")
IP = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")


def load(n, d):
    try:
        with open(os.path.join(DIR, n), encoding="utf-8") as f:
            return {**d, **json.load(f)}
    except Exception:
        return dict(d)


def save(n, v):
    with open(os.path.join(DIR, n), "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False, indent=1)


def norm(m): return m.lower().replace("-", ":")


def rows(html):
    for tr in re.findall(r"<tr.*?>(.*?)</tr>", html, re.S | re.I):
        yield [re.sub(r"<.*?>", "", c).strip() for c in re.findall(r"<t[dh].*?>(.*?)</t[dh]>", tr, re.S | re.I)]


class Router:
    def __init__(s, c): s.c = c

    def get(s, path, params=None):
        url = "http://%s%s" % (s.c["host"], path)
        if params: url += "?" + urllib.parse.urlencode(params)
        r = urllib.request.Request(url)
        r.add_header("Authorization", "Basic " + base64.b64encode(("%s:%s" % (s.c["user"], s.c["pass"])).encode()).decode())
        r.add_header("Referer", "http://%s/" % s.c["host"])
        with urllib.request.urlopen(r, timeout=6) as f:
            return f.read().decode("utf-8", "ignore")

    def clients(s):
        wifi, dh = set(), {}
        try: wifi = {norm(m) for m in MAC.findall(s.get(s.c["p_wifi"]))}
        except Exception: pass
        try:
            for r in rows(s.get(s.c["p_dhcp"])):
                macs = [x for x in r if MAC.fullmatch(x)]
                if not macs: continue
                ip = next((x for x in r if IP.fullmatch(x)), "")
                name = next((x for x in r if x and not MAC.fullmatch(x) and not IP.fullmatch(x) and not x.isdigit()), "")
                dh[norm(macs[-1])] = (name, ip)
        except Exception: pass
        if not wifi and not dh: raise RuntimeError("ما قدرت أقرأ الأجهزة (جرّب زر تشخيص)")
        return [{"mac": m, "name": dh.get(m, ("", ""))[0], "ip": dh.get(m, ("", ""))[1],
                 "on": (m in wifi) or not wifi} for m in sorted(wifi | set(dh))]

    def skey(s):
        m = re.search(r"sessionKey\s*[=:]\s*['\"]?(\d+)", s.get(s.c["p_tod"]))
        return m.group(1) if m else ""

    def block(s, mac, name):
        p = {"action": "add", "username": re.sub(r"\W", "", name or "dev")[:15] or "dev", "mac": mac,
             "days": "127", "start_time": "0", "end_time": "1439"}
        k = s.skey()
        if k: p["sessionKey"] = k
        s.get(s.c["p_add"], p)
        return mac in s.get(s.c["p_tod"]).lower()

    def unblock(s, mac):
        p = {"action": "remove", "rmLst": mac}
        k = s.skey()
        if k: p["sessionKey"] = k
        s.get(s.c["p_del"], p)
        return mac not in s.get(s.c["p_tod"]).lower()

    def diag(s):
        todo = ["/"] + [s.c[k] for k in ("p_dhcp", "p_wifi", "p_tod")]
        seen, out = set(), []
        while todo and len(seen) < 40:
            p = todo.pop(0)
            if p in seen: continue
            seen.add(p)
            try: h = s.get(p)
            except Exception as e:
                out.append("== %s ERR %s" % (p, e)); continue
            out.append("== %s len=%d macs=%d sessionKey=%s forms=%s\n%s" % (
                p, len(h), len(MAC.findall(h)), "sessionKey" in h, re.findall(r"<form[^>]*>", h, re.I)[:3], h[:800]))
            for l in re.findall(r"['\"=(]\s*/?([\w\-./]+\.(?:html|htm|cmd|tmp|asp|cgi|xml))", h):
                todo.append("/" + l)
        return "\n\n".join(out)


class App:
    def __init__(s):
        s.cfg = load("config.json", DEF)
        s.blocks = load("blocks.json", {})
        s.r = Router(s.cfg)
        s.online, s.cl = set(), []
        s.silent = not s.cfg["known"]
        s.first = True
        s.root = tk.Tk()
        s.root.title("مدير الواي فاي")
        s.root.geometry("780x540")
        bar = ttk.Frame(s.root); bar.pack(fill="x", padx=6, pady=6)
        for t, f in [("حظر مؤقت", s.tblock), ("حظر دائم", s.pblock), ("رفع الحظر", s.unb),
                     ("تسمية", s.rename), ("إعدادات", s.settings), ("تشخيص", s.diag)]:
            ttk.Button(bar, text=t, command=f).pack(side="left", padx=2)
        cols = ("st", "name", "ip", "mac", "bl")
        s.tv = ttk.Treeview(s.root, columns=cols, show="headings", height=12)
        for c, t, w in zip(cols, ("الحالة", "الاسم", "IP", "MAC", "الحظر"), (70, 200, 110, 150, 150)):
            s.tv.heading(c, text=t); s.tv.column(c, width=w)
        s.tv.pack(fill="both", expand=True, padx=6)
        s.log = tk.Text(s.root, height=9, state="disabled"); s.log.pack(fill="x", padx=6, pady=6)
        threading.Thread(target=s.loop, daemon=True).start()
        s.root.mainloop()

    def say(s, m):
        def w():
            s.log.config(state="normal"); s.log.insert("end", "[%s] %s\n" % (datetime.now().strftime("%H:%M:%S"), m))
            s.log.see("end"); s.log.config(state="disabled")
        s.root.after(0, w)

    def bg(s, f, *a): threading.Thread(target=f, args=a, daemon=True).start()

    def label(s, m):
        c = next((x for x in s.cl if x["mac"] == m), {})
        return s.cfg["names"].get(m) or c.get("name") or m

    def loop(s):
        while True:
            try:
                s.root.after(0, s.show, s.r.clients())
            except Exception as e:
                s.say("خطأ اتصال: %s" % e)
            now = time.time()
            for m, t in list(s.blocks.items()):
                if t and t < now: s.do_unblock(m)
            time.sleep(s.cfg["interval"])

    def show(s, cl):
        on = {c["mac"] for c in cl if c["on"]}
        s.cl = cl
        if not s.first:
            for m in on - s.online: s.say("اتصل: %s" % s.label(m))
            for m in s.online - on: s.say("انقطع: %s" % s.label(m))
        for c in cl:
            if c["mac"] not in s.cfg["known"]:
                s.cfg["known"].append(c["mac"])
                if not s.silent: s.say("⚠ جهاز جديد: %s (%s)" % (s.label(c["mac"]), c["mac"])); s.root.bell()
        save("config.json", s.cfg)
        s.first, s.silent, s.online = False, False, on
        sel = s.tv.selection()
        s.tv.delete(*s.tv.get_children())
        seen = set()
        for c in cl + [{"mac": m, "name": "", "ip": "", "on": False} for m in s.blocks if m not in {x["mac"] for x in cl}]:
            m = c["mac"]
            if m in seen: continue
            seen.add(m)
            b = ""
            if m in s.blocks:
                t = s.blocks[m]
                b = "دائم" if not t else "حتى " + datetime.fromtimestamp(t).strftime("%H:%M")
            s.tv.insert("", "end", iid=m, values=("متصل" if c["on"] else "-", s.label(m), c["ip"], m, b))
        if sel and s.tv.exists(sel[0]): s.tv.selection_set(sel[0])

    def sel(s):
        x = s.tv.selection()
        if not x: s.say("اختر جهازًا من القائمة أولًا")
        return x[0] if x else None

    def do_block(s, m, exp):
        try:
            if s.r.block(m, s.label(m)):
                s.blocks[m] = exp; save("blocks.json", s.blocks); s.say("تم حظر %s" % s.label(m))
            else: s.say("فشل الحظر. اضغط تشخيص وابعث لي الملف diagnostics.txt")
        except Exception as e: s.say("خطأ: %s" % e)

    def do_unblock(s, m):
        try:
            if s.r.unblock(m):
                s.blocks.pop(m, None); save("blocks.json", s.blocks); s.say("رُفع الحظر عن %s" % s.label(m))
            else: s.say("فشل رفع الحظر عن %s" % m)
        except Exception as e: s.say("خطأ: %s" % e)

    def tblock(s):
        m = s.sel()
        n = m and simpledialog.askinteger("حظر مؤقت", "المدة بالدقائق:", minvalue=1, maxvalue=10080)
        if n: s.bg(s.do_block, m, time.time() + n * 60)

    def pblock(s):
        m = s.sel()
        if m: s.bg(s.do_block, m, 0)

    def unb(s):
        m = s.sel()
        if m: s.bg(s.do_unblock, m)

    def rename(s):
        m = s.sel()
        n = m and simpledialog.askstring("تسمية", "الاسم الجديد:")
        if n: s.cfg["names"][m] = n; save("config.json", s.cfg); s.show(s.cl)

    def settings(s):
        for k, t in (("host", "عنوان الراوتر"), ("user", "المستخدم"), ("pass", "كلمة السر")):
            v = simpledialog.askstring("إعدادات", t + ":", initialvalue=s.cfg[k])
            if v: s.cfg[k] = v
        save("config.json", s.cfg)

    def diag(s):
        def f():
            s.say("جاري التشخيص...")
            try:
                with open(os.path.join(DIR, "diagnostics.txt"), "w", encoding="utf-8") as fh: fh.write(s.r.diag())
                s.say("تم حفظ diagnostics.txt بجانب البرنامج")
            except Exception as e: s.say("خطأ: %s" % e)
        s.bg(f)


if __name__ == "__main__":
    App()
