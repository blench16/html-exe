"""启动器模板：生成的每个应用 exe 都是它 + 附加的网页数据。"""
import os, sys, io, json, zipfile, hashlib, shutil, subprocess, ctypes
from pathlib import Path
import payload


def msg(text, title="提示"):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:
        print(text)


def data_root():
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "HTMLApps")


def extract(data):
    root = os.path.join(data_root(), hashlib.sha1(data).hexdigest()[:12])
    ok = os.path.join(root, ".ok")
    if not os.path.exists(ok):
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(os.path.join(root, "app"))
        open(ok, "w").close()
    return os.path.join(root, "app")


def find_browser():
    roots = [os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
             os.environ.get("LOCALAPPDATA", "")]
    for r in roots:
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            p = os.path.join(r, rel)
            if r and os.path.exists(p):
                return p
    return shutil.which("msedge") or shutil.which("chrome")


def run_browser(cfg, entry):
    b = find_browser()
    if not b:
        msg("没有找到 WebView2 组件，也没有找到 Edge 或 Chrome 浏览器。", cfg["title"])
        return
    prof = os.path.join(data_root(), "_profiles", cfg["title"])
    subprocess.Popen([b, f"--app={Path(entry).as_uri()}", f"--user-data-dir={prof}",
                      f"--window-size={cfg['width']},{cfg['height']}",
                      "--no-first-run", "--no-default-browser-check"])


class Api:
    def open_url(self, url):
        import webbrowser
        if str(url).startswith(("http://", "https://")):
            webbrowser.open(url)


def run_webview(cfg, entry):
    import webview
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True  # 允许网页里的“下载”按钮
    except Exception:
        pass
    webview.create_window(cfg["title"], entry, width=cfg["width"], height=cfg["height"], js_api=Api())
    webview.start(gui="edgechromium", private_mode=False,
                  storage_path=os.path.join(data_root(), "_storage", cfg["title"]))


def main():
    data = payload.read(sys.executable)
    if data is None:
        msg("这是启动器模板，不能单独运行。\n请用 HTML2EXE 打包器生成应用。")
        return
    app = extract(data)
    with open(os.path.join(app, "app.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    entry = os.path.join(app, cfg["entry"])
    if "--selftest" in sys.argv:
        sys.exit(0 if os.path.exists(entry) else 2)
    try:
        run_webview(cfg, entry)
    except Exception:
        run_browser(cfg, entry)


try:
    main()
except SystemExit:
    raise
except Exception:
    import traceback
    msg(traceback.format_exc()[-1000:], "应用出错")
