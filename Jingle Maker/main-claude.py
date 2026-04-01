"""
Jingle Maker Pro
----------------
Auto-installs pip dependencies into ./deps on first run.
Only external requirement: ffmpeg must be installed on the system.
"""

# ── 0. Bootstrap deps ─────────────────────────────────────────────────────────
import sys, os, subprocess

DEPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deps")
os.makedirs(DEPS_DIR, exist_ok=True)
if DEPS_DIR not in sys.path:
    sys.path.insert(0, DEPS_DIR)

REQUIRED = {
    "customtkinter": "customtkinter",
    "yt_dlp":        "yt-dlp",
    "pygame":        "pygame",
    "PIL":           "Pillow",
    "requests":      "requests",
}

def _ensure_deps():
    missing = []
    for imp, pkg in REQUIRED.items():
        try:
            __import__(imp)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[JingleMaker] Installing: {missing}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--upgrade",
             "--target", DEPS_DIR] + missing,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "--upgrade",
             "--target", DEPS_DIR, "--quiet"] + list(REQUIRED.values()),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

_ensure_deps()

# ── 1. Imports ────────────────────────────────────────────────────────────────
import customtkinter as ctk
from tkinter import filedialog, messagebox
import yt_dlp
import pygame
import threading
import hashlib
import re
import urllib.parse
import ssl

import requests
from PIL import Image
from io import BytesIO

# ── 2. SSL fix ────────────────────────────────────────────────────────────────
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass

# ── 3. ffmpeg detection ───────────────────────────────────────────────────────
def _find_ffmpeg():
    candidates = ["ffmpeg"]
    if sys.platform == "darwin":
        candidates += ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"]
    elif sys.platform == "win32":
        candidates += [os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe")]
    for c in candidates:
        try:
            subprocess.run([c, "-version"], capture_output=True, check=True)
            return c
        except Exception:
            pass
    return "ffmpeg"

FFMPEG = _find_ffmpeg()

# ── 4. Platform detection ─────────────────────────────────────────────────────
# More-specific patterns listed first so they win over shorter ones
PLATFORM_MAP = [
    (["game boy advance", "gba"],                   "Game Boy Advance"),
    (["game boy color", "gbc"],                     "Game Boy Color"),
    (["game boy", "/gb/", "\\gb\\", " gb "],        "Game Boy"),
    (["nintendo ds", "nds", "/ds/", "\\ds\\"],      "Nintendo DS"),
    (["nintendo 3ds", "3ds"],                       "Nintendo 3DS"),
    (["nintendo 64", "n64", "v64", "z64"],          "Nintendo 64"),
    (["super nintendo", "super nes", "snes", "sfc"], "Super Nintendo"),
    (["famicom", "nes"],                            "NES"),
    (["playstation 2", "ps2"],                      "PlayStation 2"),
    (["playstation", "psx", "psp"],                 "PlayStation"),
    (["genesis", "mega drive", "megadrive"],        "Sega Genesis"),
    (["game gear"],                                 "Game Gear"),
    (["master system"],                             "Master System"),
]

EXT_PLATFORM = {
    "gba": "Game Boy Advance",
    "gbc": "Game Boy Color",
    "gb":  "Game Boy",
    "nds": "Nintendo DS",
    "3ds": "Nintendo 3DS",
    "n64": "Nintendo 64",
    "v64": "Nintendo 64",
    "z64": "Nintendo 64",
    "sfc": "Super Nintendo",
    "nes": "NES",
    "iso": "PlayStation",
}

def _platform_hint(game_path: str) -> str:
    # Use full path lowercased so folder names like "Game Boy Advance" match
    full_lower = game_path.lower().replace("\\", "/")
    ext = os.path.splitext(game_path)[1].lstrip(".").lower()
    for keywords, name in PLATFORM_MAP:
        for kw in keywords:
            if kw in full_lower:
                return name
    return EXT_PLATFORM.get(ext, "")

# ── 5. Box-art fetching ───────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": "https://www.google.com/",
}

BAD_KEYWORDS = [
    "japan", "jpn", "_jp_", "-jp-", "/jp/", "japanese",
    "manual", "back", "spine", "cart", "cartridge",
    "screenshot", "disc", "media", "insert", "interior",
    "instruction", "booklet", "inlay", "overlay",
]

def _is_bad_url(url: str) -> bool:
    u = url.lower()
    return any(k in u for k in BAD_KEYWORDS)

def _is_portrait(img: Image.Image) -> bool:
    w, h = img.size
    return h >= w * 0.75

def _load_url(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGB")
        return img if img.width > 60 and img.height > 60 else None
    except Exception:
        return None

def _fetch_launchbox(game_name: str, platform: str) -> list:
    """LaunchBox Games DB public API — no key required."""
    urls = []
    try:
        plat_enc = urllib.parse.quote(platform or "")
        name_enc = urllib.parse.quote(game_name)
        api = (
            f"https://gamesdb.launchbox-app.com/api/GetGamesList"
            f"?name={name_enc}&platform={plat_enc}"
        )
        r = requests.get(api, headers=HEADERS, timeout=8)
        ids = re.findall(r'<id>(\d+)</id>', r.text)
        if not ids:
            return urls
        game_id = ids[0]
        img_api = f"https://gamesdb.launchbox-app.com/api/GetImagesByGameID/{game_id}"
        r2 = requests.get(img_api, headers=HEADERS, timeout=8)
        file_names   = re.findall(r'<fileName>(.*?)</fileName>',   r2.text)
        region_tags  = re.findall(r'<region>(.*?)</region>',       r2.text)
        type_tags    = re.findall(r'<imageType>(.*?)</imageType>', r2.text)
        for i, fn in enumerate(file_names):
            region = region_tags[i] if i < len(region_tags) else ""
            itype  = type_tags[i]   if i < len(type_tags)   else ""
            if "Front" not in itype and "Box" not in itype:
                continue
            if any(j in region for j in ("Japan", "Jpn")):
                continue
            urls.append(f"https://images.launchbox-app.com/{fn}")
    except Exception:
        pass
    return urls

def _fetch_screenscraper(game_name: str, platform: str) -> list:
    """ScreenScraper guest API — rate-limited but keyless."""
    urls = []
    try:
        q = urllib.parse.quote(game_name)
        api = (
            f"https://www.screenscraper.fr/api2/jeuInfos.php"
            f"?devid=Gemini&devpassword=&softname=JingleMakerPro"
            f"&output=json&romnom={q}&ssid=&sspassword="
        )
        r = requests.get(api, headers=HEADERS, timeout=8)
        data   = r.json()
        medias = data.get("response", {}).get("jeu", {}).get("medias", [])
        for m in medias:
            if m.get("type") not in ("box-2D", "box-2D-face", "box-3D"):
                continue
            region = m.get("region", "")
            if region in ("jp", "ja") and region != "us":
                continue
            url = m.get("url", "")
            if url:
                urls.append(url)
    except Exception:
        pass
    return urls

def _fetch_bing(game_name: str, platform: str) -> list:
    """Bing image search — last resort, filtered heavily."""
    urls = []
    try:
        plat_str = f" {platform}" if platform else ""
        q = (
            f'"{game_name}"{plat_str} "front" "box art" USA '
            f'-Japan -Japanese -manual -back -spine'
        )
        encoded = urllib.parse.quote(q)
        bing = f"https://www.bing.com/images/search?q={encoded}&qft=+filterui:imagesize-medium&first=1"
        r = requests.get(bing, headers=HEADERS, timeout=10)
        raw = re.findall(r'murl&quot;:&quot;(.*?)&quot;', r.text)
        for u in raw:
            if not _is_bad_url(u):
                urls.append(u)
            if len(urls) >= 10:
                break
    except Exception:
        pass
    return urls

def fetch_best_art(game_name: str, game_path: str):
    """Try sources in order; return first portrait-ish front-box PIL Image, or None."""
    platform = _platform_hint(game_path)

    all_urls = []

    for source_fn in [
        lambda: _fetch_launchbox(game_name, platform),
        lambda: _fetch_screenscraper(game_name, platform),
        lambda: _fetch_bing(game_name, platform),
    ]:
        urls = source_fn()
        new_urls = [u for u in urls if u not in all_urls]
        all_urls.extend(new_urls)

        for url in new_urls:
            if _is_bad_url(url):
                continue
            img = _load_url(url)
            if img and _is_portrait(img):
                return img

        if len(all_urls) >= 6:
            break

    # Second pass: accept any loadable image regardless of aspect ratio
    for url in all_urls:
        img = _load_url(url)
        if img:
            return img

    return None

# ── 6. Palette & fonts ────────────────────────────────────────────────────────
C = {
    "bg":         "#0d1117",
    "surface":    "#161b22",
    "surface2":   "#1c2128",
    "border":     "#30363d",
    "accent":     "#00c9a7",
    "accent_dim": "#00a88d",
    "blue":       "#3b82f6",
    "blue_dim":   "#2563eb",
    "muted":      "#6e7681",
    "text":       "#e6edf3",
    "text_dim":   "#8b949e",
    "skip":       "#3d444d",
    "skip_dim":   "#2d333b",
    "red":        "#f85149",
    "red_dim":    "#da3633",
    "gold":       "#d29922",
}

if sys.platform == "darwin":
    F_DISPLAY = "SF Pro Display"
    F_TEXT    = "SF Pro Text"
    F_MONO    = "SF Mono"
else:
    F_DISPLAY = "Segoe UI"
    F_TEXT    = "Segoe UI"
    F_MONO    = "Consolas"

# ── 7. Borderless popup helper ────────────────────────────────────────────────
class BarePopup(ctk.CTkToplevel):
    """
    Borderless popup centered over its parent window.
    Children should pack/grid into self.body.
    The popup is draggable by its title bar.
    """
    def __init__(self, parent, title: str, width: int, height: int):
        super().__init__(parent)
        self.overrideredirect(True)
        self.configure(fg_color=C["surface"])
        self.resizable(False, False)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - width)  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        self.geometry(f"{width}x{height}+{px}+{py}")

        self._drag_x = 0
        self._drag_y = 0

        # Custom title bar
        bar = ctk.CTkFrame(self, fg_color=C["surface2"], height=36, corner_radius=0)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        bar.bind("<ButtonPress-1>", self._drag_start)
        bar.bind("<B1-Motion>",     self._drag_move)

        ctk.CTkLabel(
            bar, text=title,
            font=(F_DISPLAY, 12, "bold"), text_color=C["text_dim"],
        ).pack(side="left", padx=14)

        ctk.CTkButton(
            bar, text="✕", width=32, height=28,
            fg_color="transparent", hover_color=C["red_dim"],
            text_color=C["muted"], font=(F_TEXT, 13),
            command=self.destroy,
        ).pack(side="right", padx=4, pady=4)

        # Thin separator under title bar
        ctk.CTkFrame(self, height=1, fg_color=C["border"], corner_radius=0).pack(fill="x")

        # Content area
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True)

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _drag_move(self, event):
        self.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")


# ── 8. Application ────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


class JingleMaker(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Jingle Maker Pro")
        self.geometry("960x820")
        self.minsize(860, 720)
        self.configure(fg_color=C["bg"])

        pygame.mixer.init()

        # State
        self.current_playing_button = None
        self.game_queue:   list = []
        self.total_in_queue   = 0
        self.processed_count  = 0
        self.current_game_path = ""
        self._overwrite_all   = False
        self.target_extensions = (
            '.gba', '.nds', '.sfc', '.nes', '.zip',
            '.gb', '.gbc', '.3ds', '.n64', '.v64', '.z64', '.iso',
        )

        # Blank 1×1 image used as the "no image" state for art_label.
        # We ALWAYS keep a CTkImage set on art_label to avoid the
        # "pyimage does not exist" crash when switching between games.
        self._blank_image = ctk.CTkImage(
            light_image=Image.new("RGB", (1, 1), (28, 33, 40)),
            dark_image =Image.new("RGB", (1, 1), (28, 33, 40)),
            size=(1, 1),
        )
        self._art_image_ref = None

        # Build UI
        self.main_frame = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=16)
        self.main_frame.pack(pady=16, padx=16, fill="both", expand=True)

        self._build_header()
        self._build_search_row()
        self._build_results()
        self._build_footer()

        self.overlay = ctk.CTkFrame(self, fg_color=C["bg"])
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ─────────────────────────────────────────────────────────────────────────
    # UI builders
    # ─────────────────────────────────────────────────────────────────────────

    def _build_header(self):
        hdr = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(20, 8))

        # Left column
        left = ctk.CTkFrame(hdr, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)

        title_row = ctk.CTkFrame(left, fg_color="transparent")
        title_row.pack(anchor="w")
        ctk.CTkLabel(
            title_row, text="Jingle Maker",
            font=(F_DISPLAY, 34, "bold"), text_color=C["text"],
        ).pack(side="left")
        ctk.CTkLabel(
            title_row, text=" Pro",
            font=(F_DISPLAY, 34, "bold"), text_color=C["accent"],
        ).pack(side="left")

        self.bulk_btn = ctk.CTkButton(
            left, text="📁  Select Root Games Folder",
            command=self.show_folder_picker,
            fg_color=C["accent"], hover_color=C["accent_dim"],
            text_color="#000000", font=(F_TEXT, 13, "bold"),
            height=36, corner_radius=8,
        )
        self.bulk_btn.pack(anchor="w", pady=(10, 0))

        self.queue_label = ctk.CTkLabel(
            left, text="Select a folder to begin",
            font=(F_DISPLAY, 18, "bold"), text_color=C["text_dim"],
        )
        self.queue_label.pack(anchor="w", pady=(14, 0))

        self.platform_label = ctk.CTkLabel(
            left, text="", font=(F_TEXT, 12), text_color=C["accent"],
        )
        self.platform_label.pack(anchor="w", pady=(2, 0))

        # Right column — art panel (fixed size)
        self._art_panel = ctk.CTkFrame(
            hdr, fg_color=C["surface2"],
            corner_radius=12, border_width=1, border_color=C["border"],
            width=200, height=260,
        )
        self._art_panel.pack(side="right", padx=(16, 0))
        self._art_panel.pack_propagate(False)

        # Accent stripe at top of panel
        ctk.CTkFrame(
            self._art_panel, height=2, fg_color=C["accent"], corner_radius=0
        ).pack(fill="x")

        # Art label — ALWAYS has a CTkImage set (blank by default)
        self.art_label = ctk.CTkLabel(
            self._art_panel,
            image=self._blank_image,
            text="No Art\nAvailable",
            font=(F_TEXT, 11), text_color=C["muted"],
            fg_color="transparent",
        )
        self.art_label.place(relx=0.5, rely=0.5, anchor="center")

    def _build_search_row(self):
        ctk.CTkFrame(
            self.main_frame, height=1, fg_color=C["border"]
        ).pack(fill="x", padx=24, pady=(8, 12))

        row = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(0, 6))

        self.search_entry = ctk.CTkEntry(
            row,
            placeholder_text="Search for a song…",
            fg_color=C["surface2"], border_color=C["border"], border_width=1,
            text_color=C["text"], placeholder_text_color=C["muted"],
            font=(F_TEXT, 13), height=38, corner_radius=8,
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.search_entry.bind("<Return>", lambda e: self.search_youtube(self.search_entry.get()))

        self.search_btn = ctk.CTkButton(
            row, text="Search",
            command=lambda: self.search_youtube(self.search_entry.get()),
            fg_color=C["blue"], hover_color=C["blue_dim"],
            height=38, width=100, corner_radius=8,
            font=(F_TEXT, 13, "bold"),
        )
        self.search_btn.pack(side="left", padx=(0, 6))

        self.skip_btn = ctk.CTkButton(
            row, text="Skip ⏭",
            command=self.next_game,
            fg_color=C["skip"], hover_color=C["skip_dim"],
            height=38, width=90, corner_radius=8,
            font=(F_TEXT, 13),
        )
        self.skip_btn.pack(side="left")

    def _build_results(self):
        self.results_frame = ctk.CTkScrollableFrame(
            self.main_frame,
            fg_color=C["surface2"],
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["accent"],
            corner_radius=10,
            label_text="Results",
            label_font=(F_TEXT, 12, "bold"),
            label_fg_color=C["surface2"],
            label_text_color=C["text_dim"],
        )
        self.results_frame.pack(pady=6, padx=24, fill="both", expand=True)

        # Trackpad / mousewheel scrolling
        self.results_frame.bind("<Enter>", lambda _: self._bind_scroll())
        self.results_frame.bind("<Leave>", lambda _: self._unbind_scroll())

    def _bind_scroll(self):
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>",   self._on_scroll_up)
        self.bind_all("<Button-5>",   self._on_scroll_down)

    def _unbind_scroll(self):
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        canvas = self.results_frame._parent_canvas
        if sys.platform == "darwin":
            canvas.yview_scroll(-event.delta, "units")
        else:
            canvas.yview_scroll(-int(event.delta / 120), "units")

    def _on_scroll_up(self, _e):
        self.results_frame._parent_canvas.yview_scroll(-1, "units")

    def _on_scroll_down(self, _e):
        self.results_frame._parent_canvas.yview_scroll(1, "units")

    def _build_footer(self):
        footer = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        footer.pack(fill="x", padx=24, pady=(6, 16))

        prog_row = ctk.CTkFrame(footer, fg_color="transparent")
        prog_row.pack(fill="x")

        self.progress_bar = ctk.CTkProgressBar(
            prog_row,
            fg_color=C["surface2"], progress_color=C["accent"],
            height=6, corner_radius=3,
        )
        self.progress_bar.set(0)
        self.progress_bar.pack(side="left", fill="x", expand=True, pady=4)

        self.progress_text = ctk.CTkLabel(
            prog_row, text="0 / 0",
            font=(F_MONO, 11), text_color=C["muted"], width=70,
        )
        self.progress_text.pack(side="left", padx=(10, 0))

        self.status_label = ctk.CTkLabel(
            footer, text="Ready",
            font=(F_TEXT, 13), text_color=C["text_dim"],
        )
        self.status_label.pack(anchor="w", pady=(2, 0))

    # ─────────────────────────────────────────────────────────────────────────
    # Box art
    # ─────────────────────────────────────────────────────────────────────────

    def _fetch_art_async(self, game_name: str):
        # Reset to blank image + "Loading…" text — safe because image is always set
        self.art_label.configure(
            image=self._blank_image,
            text="Loading…",
            text_color=C["muted"],
        )
        self._art_image_ref = None

        def worker():
            img = fetch_best_art(game_name, self.current_game_path)
            if img:
                self.after(0, self._show_art, img)
            else:
                self.after(0, lambda: self.art_label.configure(
                    image=self._blank_image,
                    text="No Art\nAvailable",
                    text_color=C["muted"],
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _show_art(self, pil_img: Image.Image):
        try:
            self._art_panel.update_idletasks()
            pw = max(self._art_panel.winfo_width()  - 16, 60)
            ph = max(self._art_panel.winfo_height() - 24, 60)
            iw, ih = pil_img.size
            scale  = min(pw / iw, ph / ih)
            nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))

            self._art_image_ref = ctk.CTkImage(
                light_image=pil_img, dark_image=pil_img, size=(nw, nh)
            )
            self.art_label.configure(image=self._art_image_ref, text="")
        except Exception as e:
            print(f"[Art] {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Folder picker
    # ─────────────────────────────────────────────────────────────────────────

    def show_folder_picker(self):
        root_dir = filedialog.askdirectory()
        self.focus_set()
        if not root_dir:
            return

        valid_paths = [
            r for r, _, files in os.walk(root_dir)
            if any(f.lower().endswith(self.target_extensions) for f in files)
        ]
        if not valid_paths:
            messagebox.showinfo("No Games", "No supported game files found.")
            return

        picker = BarePopup(self, "Select Folders", 640, 540)

        ctk.CTkLabel(
            picker.body, text="Choose which folders to include:",
            font=(F_DISPLAY, 15, "bold"), text_color=C["text"],
        ).pack(pady=(16, 6), padx=24, anchor="w")

        scroll = ctk.CTkScrollableFrame(
            picker.body, fg_color=C["surface"],
            scrollbar_button_color=C["border"],
        )
        scroll.pack(pady=4, padx=20, fill="both", expand=True)

        checkboxes = []
        all_var = ctk.BooleanVar(value=True)

        def toggle_all():
            for _, v in checkboxes:
                v.set(all_var.get())

        ctk.CTkCheckBox(
            scroll, text="SELECT ALL", variable=all_var, command=toggle_all,
            font=(F_TEXT, 13, "bold"),
            checkmark_color=C["bg"], fg_color=C["accent"], hover_color=C["accent_dim"],
        ).pack(anchor="w", pady=(4, 8))

        for path in valid_paths:
            var = ctk.BooleanVar(value=True)
            display = os.path.relpath(path, root_dir)
            ctk.CTkCheckBox(
                scroll,
                text=display if display != "." else "Root Folder",
                variable=var,
                checkmark_color=C["bg"], fg_color=C["accent"], hover_color=C["accent_dim"],
            ).pack(anchor="w", pady=2)
            checkboxes.append((path, var))

        def confirm():
            all_q, new_q, done_q = [], [], []
            for path, var in checkboxes:
                if not var.get():
                    continue
                for f in os.listdir(path):
                    if f.lower().endswith(self.target_extensions):
                        fp = os.path.join(path, f)
                        jp = os.path.join(path, f"{os.path.splitext(f)[0]} - Jingle.ogg")
                        all_q.append(fp)
                        (done_q if os.path.exists(jp) else new_q).append(fp)

            if not all_q:
                picker.destroy()
                return

            if done_q:
                dup = BarePopup(self, "Existing Jingles Found", 460, 270)

                ctk.CTkLabel(
                    dup.body,
                    text=f"Found {len(all_q)} games\n{len(done_q)} already have jingles.",
                    font=(F_DISPLAY, 15, "bold"), text_color=C["text"],
                ).pack(pady=(24, 6))
                ctk.CTkLabel(
                    dup.body,
                    text='"Search All" will silently overwrite existing jingles.',
                    font=(F_TEXT, 12), text_color=C["text_dim"],
                ).pack()

                def start_queue(q, overwrite: bool):
                    self._overwrite_all  = overwrite
                    self.game_queue      = q
                    self.total_in_queue  = len(q)
                    self.processed_count = 0
                    dup.destroy()
                    picker.destroy()
                    self._update_progress()
                    self.next_game()

                btn_row = ctk.CTkFrame(dup.body, fg_color="transparent")
                btn_row.pack(pady=18)
                ctk.CTkButton(
                    btn_row, text="Skip Done", width=130, height=36,
                    fg_color=C["accent"], hover_color=C["accent_dim"], text_color="#000000",
                    command=lambda: start_queue(new_q, False),
                ).pack(side="left", padx=8)
                ctk.CTkButton(
                    btn_row, text="Search All (Overwrite)", width=180, height=36,
                    fg_color=C["blue"], hover_color=C["blue_dim"],
                    command=lambda: start_queue(all_q, True),
                ).pack(side="left", padx=8)
            else:
                self._overwrite_all  = False
                self.game_queue      = all_q
                self.total_in_queue  = len(all_q)
                self.processed_count = 0
                picker.destroy()
                self._update_progress()
                self.next_game()

        ctk.CTkButton(
            picker.body, text="Continue →",
            command=confirm,
            fg_color=C["accent"], hover_color=C["accent_dim"],
            text_color="#000000", font=(F_TEXT, 13, "bold"),
            height=38, corner_radius=8,
        ).pack(pady=10)

    # ─────────────────────────────────────────────────────────────────────────
    # Queue flow
    # ─────────────────────────────────────────────────────────────────────────

    def _update_progress(self):
        if self.total_in_queue > 0:
            self.progress_bar.set(self.processed_count / self.total_in_queue)
            self.progress_text.configure(text=f"{self.processed_count} / {self.total_in_queue}")
        else:
            self.progress_bar.set(0)
            self.progress_text.configure(text="0 / 0")

    def next_game(self):
        self.stop_audio()
        self._clear_cache()

        if not self.game_queue:
            self._show_completion()
            return

        self.current_game_path = self.game_queue.pop(0)
        self.processed_count  += 1
        self._update_progress()

        base = os.path.splitext(os.path.basename(self.current_game_path))[0]
        jingle_path = os.path.join(
            os.path.dirname(self.current_game_path), f"{base} - Jingle.ogg"
        )

        if os.path.exists(jingle_path) and not self._overwrite_all:
            # Per-game conflict dialog only when NOT in overwrite-all mode
            self._show_conflict_dialog(base, jingle_path)
        else:
            if os.path.exists(jingle_path):
                try:
                    os.remove(jingle_path)
                except Exception:
                    pass
            self._trigger_search(base)

    def _show_conflict_dialog(self, base_name: str, jingle_path: str):
        dlg = BarePopup(self, "Existing Jingle", 420, 210)

        ctk.CTkLabel(
            dlg.body,
            text=f"'{base_name}'\nalready has a jingle.",
            font=(F_DISPLAY, 14, "bold"), text_color=C["text"],
        ).pack(pady=(24, 8))

        btn_row = ctk.CTkFrame(dlg.body, fg_color="transparent")
        btn_row.pack(pady=8)

        def choose(action: str):
            dlg.destroy()
            if action == "replace":
                try:
                    os.remove(jingle_path)
                except Exception:
                    pass
                self._trigger_search(base_name)
            elif action == "skip":
                self.next_game()
            elif action == "stop":
                self.game_queue.clear()
                self._update_progress()

        ctk.CTkButton(
            btn_row, text="Replace", width=110, height=34,
            fg_color=C["red"], hover_color=C["red_dim"],
            command=lambda: choose("replace"),
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            btn_row, text="Skip", width=110, height=34,
            fg_color=C["skip"], hover_color=C["skip_dim"],
            command=lambda: choose("skip"),
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            btn_row, text="Stop Queue", width=110, height=34,
            fg_color=C["surface2"], hover_color=C["border"],
            command=lambda: choose("stop"),
        ).pack(side="left", padx=6)

    def _trigger_search(self, base: str):
        clean    = re.sub(r'\[.*?\]|\(.*?\)', '', base).strip()
        platform = _platform_hint(self.current_game_path)

        self.queue_label.configure(text=clean, text_color=C["text"])
        self.platform_label.configure(text=platform)

        # Search query: game name + "theme song" only — no platform, no source mention
        query = f"{clean} theme song"
        self.search_entry.delete(0, "end")
        self.search_entry.insert(0, query)

        self._fetch_art_async(clean)
        self.search_youtube(query)

    # ─────────────────────────────────────────────────────────────────────────
    # Search
    # ─────────────────────────────────────────────────────────────────────────

    def search_youtube(self, query: str):
        if not query:
            return
        self.stop_audio()
        for w in self.results_frame.winfo_children():
            w.destroy()
        self.status_label.configure(text="Searching…", text_color=C["blue"])

        def worker():
            opts = {
                'quiet': True, 'no_warnings': True,
                'extract_flat': True,
                'match_filter': yt_dlp.utils.match_filter_func("duration < 1200"),
            }
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info    = ydl.extract_info(f"ytsearch20:{query}", download=False)
                    entries = [e for e in info.get('entries', []) if e][:10]
                    for e in entries:
                        if (e.get('duration') or 0) > 480:
                            continue
                        self.after(0, self._add_result_row, {
                            'title': e.get('title', 'Unknown'),
                            'url':   e.get('url') or e.get('webpage_url'),
                        })
                self.after(0, lambda: self.status_label.configure(
                    text="Ready", text_color=C["text_dim"]))
            except Exception as ex:
                print(f"[Search] {ex}")
                self.after(0, lambda: self.status_label.configure(
                    text="Search error", text_color=C["red"]))

        threading.Thread(target=worker, daemon=True).start()

    def _add_result_row(self, data: dict):
        row = ctk.CTkFrame(self.results_frame, fg_color=C["surface"], corner_radius=6)
        row.pack(fill="x", pady=3, padx=4)

        play_btn = ctk.CTkButton(
            row, text="▶", width=36, height=30,
            fg_color=C["accent"], hover_color=C["accent_dim"],
            text_color="#000000", corner_radius=6,
        )
        play_btn.configure(command=lambda b=play_btn, u=data['url']: self.toggle_preview(b, u))
        play_btn.pack(side="left", padx=(6, 4), pady=4)

        ctk.CTkLabel(
            row, text=data['title'][:85],
            font=(F_TEXT, 11), text_color=C["text"], anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=4)

        ctk.CTkButton(
            row, text="Save & Next →", width=120, height=30,
            fg_color=C["blue"], hover_color=C["blue_dim"],
            corner_radius=6, font=(F_TEXT, 11, "bold"),
            command=lambda: self._save_and_next(data),
        ).pack(side="right", padx=(4, 6), pady=4)

    # ─────────────────────────────────────────────────────────────────────────
    # Audio preview
    # ─────────────────────────────────────────────────────────────────────────

    def toggle_preview(self, button, url: str):
        if self.current_playing_button is button:
            self.stop_audio()
            return
        self.stop_audio()
        self.current_playing_button = button
        cache = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f"cache_{hashlib.md5(url.encode()).hexdigest()}.mp3",
        )
        if os.path.exists(cache):
            self._play_file(cache, button)
        else:
            button.configure(text="⏳", fg_color=C["gold"])
            threading.Thread(
                target=self._dl_preview, args=(url, button, cache), daemon=True
            ).start()

    def _dl_preview(self, url: str, button, cache: str):
        opts = {
            'format': 'bestaudio/best',
            'outtmpl': cache.replace('.mp3', ''),
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}],
            'quiet': True, 'no_warnings': True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            if os.path.exists(cache):
                self.after(0, lambda: self._play_file(cache, button))
        except Exception:
            self.after(0, self.stop_audio)

    def _play_file(self, path: str, button):
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            button.configure(text="⏹", fg_color=C["red"], hover_color=C["red_dim"])
        except Exception:
            self.stop_audio()

    def stop_audio(self):
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
        if self.current_playing_button:
            try:
                self.current_playing_button.configure(
                    text="▶", fg_color=C["accent"], hover_color=C["accent_dim"],
                    text_color="#000000",
                )
            except Exception:
                pass
        self.current_playing_button = None

    # ─────────────────────────────────────────────────────────────────────────
    # Download & save
    # ─────────────────────────────────────────────────────────────────────────

    def _save_and_next(self, data: dict):
        self.stop_audio()
        folder   = os.path.dirname(self.current_game_path)
        basename = os.path.splitext(os.path.basename(self.current_game_path))[0]
        filename = f"{basename} - Jingle"
        threading.Thread(
            target=self._process_download, args=(data['url'], folder, filename), daemon=True
        ).start()

    def _process_download(self, url: str, folder: str, filename: str):
        raw_base = os.path.join(folder, f"{filename}_raw")
        final    = os.path.join(folder, f"{filename}.ogg")

        for ext in ('.opus', '.ogg', '.webm', '.m4a', '.mp3'):
            try:
                os.remove(raw_base + ext)
            except FileNotFoundError:
                pass

        opts = {
            'format': 'bestaudio/best', 'quiet': True, 'no_warnings': True,
            'outtmpl': raw_base,
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'opus'}],
        }
        try:
            self.after(0, lambda: self.status_label.configure(
                text="Downloading…", text_color=C["gold"]))
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            raw_file = next(
                (raw_base + ext for ext in ('.opus', '.ogg', '.webm', '.m4a', '.mp3')
                 if os.path.exists(raw_base + ext)),
                None,
            )
            if raw_file:
                self.after(0, lambda: self.status_label.configure(
                    text="Mastering…", text_color=C["blue"]))
                subprocess.run([
                    FFMPEG, '-y', '-i', raw_file,
                    '-t', '30',
                    '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11,afade=t=out:st=28:d=2',
                    '-c:a', 'libopus', '-b:a', '128k', final,
                ], check=True, capture_output=True)
                os.remove(raw_file)

            self.after(0, self.next_game)
        except Exception as ex:
            print(f"[Download] {ex}")
            self.after(0, lambda: self.status_label.configure(
                text="Download failed", text_color=C["red"]))

    # ─────────────────────────────────────────────────────────────────────────
    # Completion screen
    # ─────────────────────────────────────────────────────────────────────────

    def _show_completion(self):
        self.overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.overlay.lift()

        win = BarePopup(self, "All Done!", 360, 210)
        win.protocol("WM_DELETE_WINDOW", lambda: self._reset(win))

        ctk.CTkLabel(
            win.body, text="✅  Library Complete!",
            font=(F_DISPLAY, 20, "bold"), text_color=C["accent"],
        ).pack(pady=(28, 6))
        ctk.CTkLabel(
            win.body, text=f"Processed {self.total_in_queue} games.",
            font=(F_TEXT, 13), text_color=C["text_dim"],
        ).pack(pady=4)
        ctk.CTkButton(
            win.body, text="Great!",
            command=lambda: self._reset(win),
            fg_color=C["accent"], hover_color=C["accent_dim"],
            text_color="#000000", height=38, width=130, corner_radius=8,
        ).pack(pady=18)

    def _reset(self, win=None):
        if win:
            win.destroy()
        self.overlay.place_forget()
        self.queue_label.configure(text="Select a folder to begin", text_color=C["text_dim"])
        self.platform_label.configure(text="")
        self.status_label.configure(text="Ready", text_color=C["text_dim"])
        self.progress_bar.set(0)
        self.progress_text.configure(text="0 / 0")
        self.art_label.configure(
            image=self._blank_image, text="No Art\nAvailable", text_color=C["muted"]
        )
        self._art_image_ref = None
        for w in self.results_frame.winfo_children():
            w.destroy()
        self.game_queue.clear()
        self.total_in_queue  = 0
        self.processed_count = 0
        self._overwrite_all  = False

    # ─────────────────────────────────────────────────────────────────────────
    # Cleanup
    # ─────────────────────────────────────────────────────────────────────────

    def _clear_cache(self):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for f in os.listdir(script_dir):
            if f.startswith("cache_") and f.endswith(".mp3"):
                try:
                    os.remove(os.path.join(script_dir, f))
                except Exception:
                    pass

    def on_closing(self):
        self.stop_audio()
        self._clear_cache()
        self.destroy()


if __name__ == "__main__":
    app = JingleMaker()
    app.mainloop()
