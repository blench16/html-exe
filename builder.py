"""HTML2EXE 打包器：选一个 HTML，生成可双击运行的独立 exe。"""
import os, sys, io, re, json, zipfile, threading, subprocess, urllib.request
from pathlib import Path
from urllib.parse import urlparse
import payload

MAX_TOTAL = 300 * 1024 * 1024
SKIP_DIRS = {"__pycache__", "node_modules", ".git"}


def resource(name):
    for base in (getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__)),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")):
        if base and os.path.exists(os.path.join(base, name)):
            return os.path.join(base, name)
    return None


def fetch_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def localize(text, log, fetch=fetch_url):
    """把网页里的在线 <script src> / <link rel=stylesheet> 下载到本地，实现离线可用。"""
    extra, cache = {}, {}

    def grab(url, ext):
        if url in cache:
            return cache[url]
        try:
            data = fetch(url)
        except Exception as e:
            log(f"  下载失败，保留在线链接：{url}（{e}）")
            cache[url] = None
            return None
        base = re.sub(r"[^\w.\-]", "_", os.path.basename(urlparse(url).path) or "file")
        if not os.path.splitext(base)[1]:
            base += ext
        name = f"_offline_libs/{len(extra)}_{base}"
        extra[name] = data
        cache[url] = name
        log(f"  已下载：{url}")
        return name

    def fix(m, attr, ext, need=None):
        tag = m.group(0)
        if need and need not in tag.lower():
            return tag
        am = re.search(r"(?<![\w-])" + attr + r"""\s*=\s*(["'])(https?://[^"']+)\1""", tag, re.I)
        if not am:
            return tag
        local = grab(am.group(2), ext)
        if not local:
            return tag
        tag = tag[:am.start(2)] + local + tag[am.end(2):]
        # file:// 下 crossorigin / integrity 可能导致脚本加载失败，去掉
        return re.sub(r"""\s(?:integrity|crossorigin)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?""", "", tag, flags=re.I)

    text = re.sub(r"<script\b[^>]*>", lambda m: fix(m, "src", ".js"), text, flags=re.I)
    text = re.sub(r"<link\b[^>]*>", lambda m: fix(m, "href", ".css", "stylesheet"), text, flags=re.I)
    return text, extra


def build_zip(html_path, include_folder, offline, title, width, height, log, skip_paths=()):
    html_path = Path(html_path).resolve()
    folder = html_path.parent
    raw = html_path.read_bytes()
    extra = {}
    if offline:
        try:
            text = raw.decode("utf-8-sig")
            log("正在检查网页里的在线资源……")
            new_text, extra = localize(text, log)
            if extra:
                raw = new_text.encode("utf-8")
            else:
                log("  没有需要下载的在线资源。")
        except UnicodeDecodeError:
            log("  网页不是 UTF-8 编码，跳过离线化。")
    entry = html_path.name if include_folder else "index.html"
    skip = {Path(p).resolve() for p in skip_paths}
    buf = io.BytesIO()
    total = len(raw)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if include_folder:
            for p in folder.rglob("*"):
                if not p.is_file() or p == html_path or p.resolve() in skip:
                    continue
                rel = p.relative_to(folder)
                if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
                    continue
                total += p.stat().st_size
                if total > MAX_TOTAL:
                    raise RuntimeError("文件夹内容超过 300MB。请只放网页需要的文件，或取消“打包整个文件夹”。")
                z.write(p, rel.as_posix())
        z.writestr(entry, raw)
        for name, data in extra.items():
            z.writestr(name, data)
        z.writestr("app.json", json.dumps(
            {"title": title, "width": width, "height": height, "entry": entry}, ensure_ascii=False))
    return buf.getvalue()


def do_build(html, out, title, width, height, include_folder, offline, log):
    stub = resource("stub.exe")
    if not stub:
        raise RuntimeError("缺少 stub.exe 模板，请用 build_all.bat 重新生成本软件。")
    if not os.path.isfile(html):
        raise RuntimeError("请先选择一个存在的 HTML 文件。")
    log("正在收集文件……")
    data = build_zip(html, include_folder, offline, title, width, height, log, skip_paths=[out])
    stub_mb = os.path.getsize(stub) / 1048576
    log(f"启动器 {stub_mb:.1f} MB + 网页数据 {len(data) / 1024:.0f} KB，正在生成 exe……")
    payload.pack(stub, data, out)
    log(f"成品大小 {os.path.getsize(out) / 1048576:.1f} MB")
    log("正在自检……")
    flags = 0x08000000 if os.name == "nt" else 0
    try:
        r = subprocess.run([out, "--selftest"], timeout=90, creationflags=flags)
        ok = r.returncode == 0
    except Exception as e:
        log(f"自检出错：{e}")
        ok = False
    log(f"完成：{out}" if ok else f"警告：已生成，但自检未通过：{out}")
    return ok


def main_gui():
    try:  # 高分屏下文字更清晰
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, font as tkfont

    BG, FG, DIM, LINE = "#ffffff", "#18181b", "#71717a", "#e4e4e7"
    PANEL, HOVER, DISABLED = "#f5f5f6", "#3f3f46", "#a1a1aa"

    root = tk.Tk()
    root.title("HTML 转 EXE")
    root.configure(bg=BG)
    scale = max(1.0, root.winfo_fpixels("1i") / 96)

    def px(n):
        return int(n * scale)

    root.geometry(f"{px(600)}x{px(680)}")
    root.minsize(px(520), px(620))

    fams = set(tkfont.families())
    ui = next((f for f in ("Microsoft YaHei UI", "Segoe UI") if f in fams), "TkDefaultFont")
    mono = next((f for f in ("Cascadia Mono", "Consolas") if f in fams), "TkFixedFont")
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        tkfont.nametofont(name).configure(family=ui, size=10)

    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", background=BG, foreground=FG, font=(ui, 10))
    st.configure("TFrame", background=BG)
    st.configure("TLabel", background=BG, foreground=FG)
    st.configure("Dim.TLabel", foreground=DIM, font=(ui, 9))
    st.configure("Title.TLabel", font=(ui, 20, "bold"))
    st.configure("TEntry", fieldbackground=BG, foreground=FG, bordercolor=LINE, lightcolor=LINE,
                 darkcolor=LINE, borderwidth=1, padding=(px(8), px(6)))
    st.map("TEntry", bordercolor=[("focus", FG)], lightcolor=[("focus", FG)], darkcolor=[("focus", FG)])
    st.configure("TButton", background=BG, foreground=FG, bordercolor=LINE, lightcolor=BG, darkcolor=BG,
                 borderwidth=1, focusthickness=0, focuscolor=BG, padding=(px(14), px(6)))
    st.map("TButton", background=[("active", PANEL)], bordercolor=[("active", DISABLED)])
    st.configure("Primary.TButton", background=FG, foreground="#ffffff", bordercolor=FG, lightcolor=FG,
                 darkcolor=FG, padding=(px(14), px(10)), font=(ui, 10, "bold"))
    st.map("Primary.TButton", background=[("disabled", DISABLED), ("active", HOVER)],
           bordercolor=[("disabled", DISABLED), ("active", HOVER)],
           lightcolor=[("disabled", DISABLED), ("active", HOVER)],
           darkcolor=[("disabled", DISABLED), ("active", HOVER)],
           foreground=[("disabled", "#ffffff")])
    st.configure("TCheckbutton", background=BG, foreground=FG, focuscolor=BG, indicatorbackground=BG,
                 indicatorforeground="#ffffff", upperbordercolor=DISABLED, lowerbordercolor=DISABLED)
    st.map("TCheckbutton", background=[("active", BG)],
           indicatorbackground=[("selected", FG), ("active", PANEL)],
           upperbordercolor=[("selected", FG)], lowerbordercolor=[("selected", FG)])
    st.configure("Thin.Horizontal.TProgressbar", troughcolor=PANEL, background=FG, bordercolor=PANEL,
                 lightcolor=FG, darkcolor=FG, thickness=px(3))

    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        desktop = Path.home()

    v_html, v_name, v_out = tk.StringVar(), tk.StringVar(value="我的应用"), tk.StringVar()
    v_w, v_h = tk.StringVar(value="1280"), tk.StringVar(value="800")
    v_folder, v_off = tk.BooleanVar(value=False), tk.BooleanVar(value=True)

    wrap = ttk.Frame(root, padding=(px(32), px(28), px(32), px(20)))
    wrap.pack(fill="both", expand=True)

    ttk.Label(wrap, text="HTML 转 EXE", style="Title.TLabel").pack(anchor="w")
    ttk.Label(wrap, text="把单个网页打包成双击即可运行的软件", style="Dim.TLabel").pack(anchor="w", pady=(px(2), px(22)))

    def label(parent, text):
        ttk.Label(parent, text=text, style="Dim.TLabel").pack(anchor="w", pady=(0, px(4)))

    def pick_html():
        p = filedialog.askopenfilename(title="选择 HTML 文件", filetypes=[("HTML", "*.html *.htm")])
        if p:
            v_html.set(p)
            v_name.set(Path(p).stem)
            v_out.set(str(desktop / (Path(p).stem + ".exe")))

    def pick_out():
        p = filedialog.asksaveasfilename(title="保存为", defaultextension=".exe", filetypes=[("程序", "*.exe")],
                                         initialfile=Path(v_out.get() or "app.exe").name)
        if p:
            v_out.set(p)

    def path_row(text, var, btn_text, cmd, top=0):
        box = ttk.Frame(wrap)
        box.pack(fill="x", pady=(top, 0))
        label(box, text)
        line = ttk.Frame(box)
        line.pack(fill="x")
        ttk.Button(line, text=btn_text, command=cmd).pack(side="right", padx=(px(8), 0))
        ttk.Entry(line, textvariable=var).pack(side="left", fill="x", expand=True)

    path_row("HTML 文件", v_html, "选择", pick_html)

    row = ttk.Frame(wrap)
    row.pack(fill="x", pady=(px(16), 0))
    lf = ttk.Frame(row)
    lf.pack(side="left", fill="x", expand=True)
    label(lf, "软件名称")
    ttk.Entry(lf, textvariable=v_name).pack(fill="x")
    rf = ttk.Frame(row)
    rf.pack(side="left", padx=(px(16), 0))
    label(rf, "窗口大小")
    sz = ttk.Frame(rf)
    sz.pack(anchor="w")
    ttk.Entry(sz, textvariable=v_w, width=6).pack(side="left")
    ttk.Label(sz, text="×", style="Dim.TLabel").pack(side="left", padx=px(6))
    ttk.Entry(sz, textvariable=v_h, width=6).pack(side="left")

    path_row("输出位置", v_out, "另存为", pick_out, top=px(16))

    opts = ttk.Frame(wrap)
    opts.pack(fill="x", pady=(px(20), 0))
    ttk.Checkbutton(opts, text="同时打包 HTML 所在文件夹", variable=v_folder).pack(anchor="w")
    ttk.Label(opts, text="仅当网页还用到同文件夹里的 CSS、JS、图片时才需要勾选",
              style="Dim.TLabel").pack(anchor="w", padx=(px(24), 0), pady=(0, px(10)))
    ttk.Checkbutton(opts, text="把在线脚本和样式下载到本地", variable=v_off).pack(anchor="w")
    ttk.Label(opts, text="打包后无需联网也能正常使用",
              style="Dim.TLabel").pack(anchor="w", padx=(px(24), 0))

    btn = ttk.Button(wrap, text="开始打包", style="Primary.TButton")
    btn.pack(fill="x", pady=(px(24), px(10)))
    bar = ttk.Progressbar(wrap, mode="indeterminate", style="Thin.Horizontal.TProgressbar")
    bar.pack(fill="x", pady=(0, px(14)))

    foot = ttk.Frame(wrap)
    foot.pack(side="bottom", fill="x", pady=(px(10), 0))
    open_btn = ttk.Button(foot, text="在文件夹中显示")

    logbox = tk.Text(wrap, height=8, state="disabled", bg=PANEL, fg=FG, relief="flat", bd=0,
                     highlightthickness=0, font=(mono, 9), padx=px(12), pady=px(10), wrap="word")
    logbox.pack(fill="both", expand=True)
    logbox.tag_config("ok", foreground="#15803d")
    logbox.tag_config("err", foreground="#b91c1c")

    def log(text):
        tag = "ok" if text.startswith("完成") else ("err" if text.startswith(("失败", "警告")) else "")

        def w():
            logbox.config(state="normal")
            logbox.insert("end", text + "\n", tag)
            logbox.see("end")
            logbox.config(state="disabled")
        root.after(0, w)

    def folder_size_over(folder, limit):
        total = 0
        for dp, dn, fn in os.walk(folder):
            dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".")]
            for f in fn:
                try:
                    total += os.path.getsize(os.path.join(dp, f))
                except OSError:
                    pass
                if total > limit:
                    return True
        return False

    def start():
        try:
            w, h = int(v_w.get()), int(v_h.get())
        except ValueError:
            return messagebox.showerror("HTML 转 EXE", "窗口大小请填数字。")
        name, out = v_name.get().strip(), v_out.get().strip()
        if not v_html.get() or not name or not out.lower().endswith(".exe"):
            return messagebox.showerror("HTML 转 EXE", "请选择 HTML 文件、填写名称，并确保输出路径以 .exe 结尾。")
        if v_folder.get() and folder_size_over(os.path.dirname(v_html.get()), 20 * 1024 * 1024):
            if not messagebox.askokcancel("HTML 转 EXE", "该文件夹超过 20 MB，会让软件变得很大。\n\n确定要把整个文件夹一起打包吗？"):
                return
        open_btn.pack_forget()
        btn.config(state="disabled", text="正在打包…")
        bar.start(12)

        def work():
            ok = False
            try:
                ok = do_build(v_html.get(), out, name, w, h, v_folder.get(), v_off.get(), log)
            except Exception as e:
                log(f"失败：{e}")

            def done():
                bar.stop()
                btn.config(state="normal", text="开始打包")
                if ok:
                    open_btn.config(command=lambda: subprocess.Popen(["explorer", "/select,", os.path.normpath(out)]))
                    open_btn.pack(anchor="e")
            root.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    btn.config(command=start)
    root.mainloop()


def _crash(text):
    import ctypes, tempfile
    p = os.path.join(tempfile.gettempdir(), "html2exe_error.txt")
    open(p, "w", encoding="utf-8").write(text)
    try:
        ctypes.windll.user32.MessageBoxW(0, "程序出错了，详情已保存到：\n" + p + "\n\n" + text[-800:], "HTML2EXE", 0x10)
    except Exception:
        print(text)


if __name__ == "__main__":
    try:
        main_gui()
    except Exception:
        import traceback
        _crash(traceback.format_exc())
